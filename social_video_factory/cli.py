"""``fire`` CLI for social_video_factory.

WHY ``fire``: it matches the repo's existing CLI surface (root ``cli.py`` /
``batch_runner.py``) and turns plain functions into subcommands with `--flag`
mapping for free, so the command surface stays a thin shell over
:mod:`social_video_factory.pipeline`.

Phase-1 commands: ``generate-one``, ``list-jobs``, ``show-job``. Later phases
add the browser commands. Documented entry point: ``python -m
social_video_factory.cli``.
"""

from __future__ import annotations

import json
import sys

import fire

from social_video_factory import config, media, pipeline
from social_video_factory.models import GenerationMode, Job
from social_video_factory.pipeline import generate_one as _generate_one
from social_video_factory.store import JobStore


def _job_summary(job: Job) -> dict[str, object]:
    """Compact, human-skimmable view of a job for CLI output."""
    return {
        "id": job.id,
        "template": job.template,
        "topic": job.topic,
        "generation_mode": job.generation_mode,
        "status": job.status,
        "provider": job.provider,
        "rendered_path": job.rendered_path,
        "imported_media_path": job.imported_media_path,
        "publish_results": job.publish_results,
    }


def generate_one(
    template: str,
    topic: str,
    generation_mode: str = GenerationMode.MOCK.value,
    target: str = "flow",
) -> None:
    """Create and run a job. For ``mock`` it runs to ``awaiting_approval``.

    Args:
        template: creative template name, e.g. ``dancing_cat``.
        topic: subject of the short, e.g. ``"orange cat disco kitchen"``.
        generation_mode: ``mock`` (default), ``browser_flow``, ``assisted_flow``,
            ``flow_import``, or ``api_veo`` (disabled).
        target: ``flow`` (default) or ``gemini`` — picks the provider marker.
    """
    # Return None so fire does not re-echo the dict on top of our JSON print.
    job = _generate_one(template, topic, generation_mode=generation_mode, target=target)
    print(json.dumps(_job_summary(job), indent=2, ensure_ascii=False))


def list_jobs(
    status: str | None = None,
    generation_mode: str | None = None,
) -> None:
    """List jobs (newest first), optionally filtered by status / mode."""
    jobs = JobStore().list_jobs(status=status, generation_mode=generation_mode)
    summaries = [_job_summary(j) for j in jobs]
    print(json.dumps(summaries, indent=2, ensure_ascii=False))


def show_job(job_id: str) -> None:
    """Print the full JSON record for a single job."""
    job = JobStore().load(job_id)
    print(json.dumps(job.to_dict(), indent=2, ensure_ascii=False))


def browser_login(target: str = "flow", url: str | None = None) -> None:
    """Log in manually in a NORMAL (non-automated) Chrome on the profile dir.

    Google/Instagram/TikTok refuse sign-in inside an automation-controlled
    browser ("this browser may not be secure"), so login MUST happen in a plain
    Chrome. We launch one on the SAME persistent profile the automation reuses;
    you sign in by hand (view it via the noVNC link), then later runs reuse that
    saved session and never log in themselves. We never bypass login.

    Args:
        target: ``flow`` (default), ``gemini``, ``instagram`` or ``tiktok``.
        url: explicit URL to open; overrides the target's default.
    """
    from social_video_factory import manual_login as ml

    try:
        if url and target.strip().lower() in {"flow", "gemini"}:
            # Honor an explicit URL override for the generation targets.
            profile = config.profile_dir()
            exe = config.browser_executable_path() or "google-chrome-stable"
            import subprocess

            cmd = ml.build_chrome_command(exe, profile, url.strip())
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                input(
                    "A normal Chrome window has opened on the virtual display.\n"
                    "View it at your noVNC link, sign in, then press Enter here..."
                )
            finally:
                proc.terminate()
            return
        ml.manual_login(target)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc


def browser_generate(job_id: str) -> None:
    """Run the conservative browser worker for a job, then continue the pipeline.

    Loads the job, ensures it has a prompt (building one if a bare job was
    created), drives ONE generation against your logged-in browser, then carries
    the result through import -> review -> render -> captions ->
    ``awaiting_approval``.  Prints the outcome as JSON and uses a distinct exit
    code per outcome so scripts can branch:

        0 success | 4 rate_limited | 3 needs_human | 1 error / browser unavailable

    Nothing is bypassed: login, usage limits, and safety screens always stop the
    worker and ask for a human.

    Args:
        job_id: the id of an existing job (see ``list-jobs`` / ``generate-one``).
    """
    from social_video_factory.browser import BrowserUnavailable, generate_in_browser

    store = JobStore()
    try:
        job = store.load(job_id)
    except FileNotFoundError:
        print(f"job not found: {job_id}", file=sys.stderr)
        raise SystemExit(2) from None

    if job.generation_mode != GenerationMode.BROWSER_FLOW.value:
        print(
            f"warning: job {job_id} mode is {job.generation_mode!r}, not "
            "'browser_flow'; proceeding anyway.",
            file=sys.stderr,
        )

    # Ensure the job has a prompt so even a bare job is usable.
    if not (job.prompt or job.prompt_path):
        pipeline.run_idea(job, store)
        pipeline.run_script(job, store)
        pipeline.run_prompt(job, store)
        pipeline.save_prompt_file(job, store)
    elif not job.prompt and job.prompt_path:
        try:
            with open(job.prompt_path, "r", encoding="utf-8") as fh:
                job.prompt = fh.read()
        except OSError:
            pass

    try:
        outcome = generate_in_browser(job, store)
    except BrowserUnavailable as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    print(
        json.dumps(
            {
                "status": outcome.status,
                "job_id": outcome.job_id,
                "downloaded_path": outcome.downloaded_path,
                "reason": outcome.reason,
            },
            indent=2,
            ensure_ascii=False,
        )
    )

    exit_codes = {"success": 0, "rate_limited": 4, "needs_human": 3, "error": 1}
    code = exit_codes.get(outcome.status, 1)
    if code:
        raise SystemExit(code)


def browser_run_queue(limit: int = 5) -> None:
    """Process up to ``limit`` pending ``browser_flow`` jobs one-by-one.

    Selects prepared-but-not-yet-generated ``browser_flow`` jobs oldest-first,
    drives each through the conservative browser worker, and PAUSES between
    successes so each generation clears the local min-gap.  The queue STOPS
    immediately on any hard stop (``needs_human``), unexpected ``error``, or
    ``rate_limited`` outcome — there is no point continuing past a screen that
    needs a human or a cap that will keep denying.

    Prints a JSON summary ``{processed, stopped_reason, outcomes: [...]}``.  The
    run itself completed and recorded every outcome, so this ALWAYS exits 0;
    when the queue stopped early the reason is also printed prominently to
    stderr so scripts/humans notice.

    Args:
        limit: maximum number of jobs to process (default 5).
    """
    from social_video_factory.browser import queue as queue_mod

    result = queue_mod.run_queue(limit)
    print(
        json.dumps(
            {
                "processed": result.processed,
                "stopped_reason": result.stopped_reason,
                "outcomes": [
                    {
                        "status": o.status,
                        "job_id": o.job_id,
                        "downloaded_path": o.downloaded_path,
                        "reason": o.reason,
                    }
                    for o in result.outcomes
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    if result.stopped_reason:
        # The run completed + recorded outcomes, so exit 0; just flag the stop.
        print(
            f"queue stopped early: {result.stopped_reason}",
            file=sys.stderr,
        )


def import_latest_browser_download(job_id: str) -> None:
    """Import the newest browser download for a job, then finish the pipeline.

    Manual-recovery path for when the worker PAUSED for a human and you clicked
    download yourself: it finds the most recent video in the configured
    downloads dir, imports it for ``job_id``, then runs the SAME post-import
    tail the worker runs (review -> render -> captions -> awaiting_approval).
    Config-gated publishing may continue after import when explicitly enabled.

    Exit codes: 0 success | 2 job not found | 5 no video download found.

    Args:
        job_id: the id of an existing job (see ``list-jobs``).
    """
    store = JobStore()
    try:
        job = store.load(job_id)
    except FileNotFoundError:
        print(f"job not found: {job_id}", file=sys.stderr)
        raise SystemExit(2) from None

    downloads = config.downloads_dir()
    latest = media.find_latest_download(downloads)
    if latest is None:
        print(f"no video download found in {downloads}", file=sys.stderr)
        raise SystemExit(5)

    # REUSE the Phase-1 stages: import + the shared review/render/captions/approval tail.
    pipeline.run_import(job, store, src_path=latest)
    pipeline.finish_after_import(job, store)

    print(json.dumps(_job_summary(job), indent=2, ensure_ascii=False))


def publish_job(job_id: str, platforms: str = "") -> None:
    """Publish a rendered job to configured Instagram/TikTok accounts."""
    from social_video_factory.publish import publish_job as _publish_job

    store = JobStore()
    try:
        job = store.load(job_id)
    except FileNotFoundError:
        print(f"job not found: {job_id}", file=sys.stderr)
        raise SystemExit(2) from None
    selected = [value.strip() for value in platforms.split(",") if value.strip()]
    try:
        _publish_job(job, store, selected or None)
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(_job_summary(job), indent=2, ensure_ascii=False))


def autopilot(target_pending: int | None = None, per_run_limit: int | None = None) -> None:
    """Run ONE unattended autopilot pass (top up queue -> generate -> alert).

    Designed to be invoked by a scheduler (systemd timer / Hermes cron) on a
    cadence. Tops up pending browser_flow jobs from the configured topic
    rotation, runs the conservative browser queue, auto-publishes when enabled
    in config, and pushes a Telegram/Discord alert if anything needs a human.
    Always exits 0 — problems are surfaced via the alert + printed summary, not
    exit codes, so the scheduler doesn't flap.

    Args:
        target_pending: keep this many pending jobs queued (default from config).
        per_run_limit: generate at most this many jobs this pass (default from config).
    """
    from social_video_factory.autopilot import run_once

    result = run_once(target_pending=target_pending, per_run_limit=per_run_limit)
    print(result.summary)


def doctor() -> None:
    """Preflight: report what's ready vs missing before enabling the loop.

    Checks dependencies (ffmpeg/Playwright), the generation target URL, seeded
    logins, notification creds, supervised-pause/noVNC, and the publishing +
    autopilot config. Exits non-zero if any hard check FAILS so it's usable as a
    gate in a setup script. Never prints secret values.
    """
    from social_video_factory import doctor as doctor_mod

    checks = doctor_mod.run_checks()
    symbol = {doctor_mod.OK: "OK  ", doctor_mod.WARN: "WARN", doctor_mod.FAIL: "FAIL"}
    for c in checks:
        print(f"[{symbol[c.level]}] {c.name}: {c.detail}")
    ok, warn, fail = doctor_mod.summarize(checks)
    print(f"\n{ok} ok, {warn} warning(s), {fail} failure(s)")
    if fail:
        raise SystemExit(1)


def notify_test(message: str = "social_video_factory: test notification ✅") -> None:
    """Send a test alert to confirm Telegram/Discord delivery works."""
    from social_video_factory.notify import notify as _notify

    sent = _notify(message)
    if sent:
        print("sent: a test notification went out to your configured channel(s).")
    else:
        print(
            "NOT sent: no channel configured (set TELEGRAM_BOT_TOKEN + "
            "TELEGRAM_HOME_CHANNEL, or SOCIAL_FACTORY_DISCORD_WEBHOOK).",
            file=sys.stderr,
        )
        raise SystemExit(1)


def main() -> None:
    """Entry point used by ``__main__`` and ``python -m ...cli``."""
    fire.Fire(
        {
            "generate-one": generate_one,
            "list-jobs": list_jobs,
            "show-job": show_job,
            "browser-login": browser_login,
            "browser-generate": browser_generate,
            "browser-run-queue": browser_run_queue,
            "import-latest-browser-download": import_latest_browser_download,
            "publish-job": publish_job,
            "autopilot": autopilot,
            "doctor": doctor,
            "notify-test": notify_test,
        }
    )


if __name__ == "__main__":
    main()
