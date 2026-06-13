"""The ``browser_flow`` worker: drive one logged-in generation, conservatively.

This is the real generation engine for ``browser_flow`` mode.  It orchestrates a
SINGLE generation against the user's OWN logged-in Chromium profile and then
hands the downloaded clip to the Phase-1 pipeline stages.

CONSERVATIVE BY DESIGN (every one of these is enforced below):
  * The LOCAL rate-limit gate runs FIRST, BEFORE the browser is ever opened.
  * Hard stops (login / CAPTCHA / limit / payment / refusal / ...) are checked
    right after navigation, after submit, AND on every poll iteration during the
    generation wait — a refusal or limit can appear mid-generation.
  * On ANY selector miss (prompt box, submit, download, ...) we fall back to
    ``resolver.manual_pause(...)`` — a human finishes that step in the open
    window; we never guess or force.
  * We NEVER bypass login, usage limits, or safety.  On a hard stop we screenshot,
    mark the job ``needs_human`` with a reason, close the browser, and return.
  * We NEVER auto-publish; success only carries the job to ``awaiting_approval``.
  * Secrets are never logged — artifacts go through ``artifacts.redact``.

Everything external (controller, rate limiter, selector config, artifact logger)
is injectable so the whole flow is testable with FAKES and no real browser.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from social_video_factory import config, media, pipeline
from social_video_factory.browser import flow_ui
from social_video_factory.browser.hard_stops import detect_hard_stop
from social_video_factory.browser.selectors import SelectorResolver, load_selector_config
from social_video_factory.models import Job, JobStatus
from social_video_factory.store import JobStore

# Outcome statuses.
STATUS_SUCCESS = "success"
STATUS_NEEDS_HUMAN = "needs_human"
STATUS_RATE_LIMITED = "rate_limited"
STATUS_ERROR = "error"


@dataclass
class GenerationOutcome:
    """Result of :func:`generate_in_browser`.

    ``status`` is one of ``success | needs_human | rate_limited | error``.
    """

    status: str
    job_id: str
    downloaded_path: str | None = None
    reason: str | None = None


def _page_text(controller: Any) -> str:
    """Best-effort VISIBLE page text for the hard-stop scan; '' on failure.

    Prefers ``visible_text()`` (what the user actually sees) so hidden menu
    items, aria labels, footers and inlined scripts don't false-trip the
    conservative hard-stop detector. Falls back to full ``html()`` for
    controllers that don't implement ``visible_text`` (e.g. older fakes).
    """
    for getter in ("visible_text", "html"):
        fn = getattr(controller, getter, None)
        if fn is None:
            continue
        try:
            text = fn()
        except Exception:
            continue
        if text:
            return text
    return ""


def _needs_human(
    job: Job,
    store: JobStore,
    controller: Any,
    artifacts: Any,
    reason: str,
    *,
    stage: str = "hard_stop",
) -> GenerationOutcome:
    """Mark a job ``needs_human``, screenshot, persist, close, and return.

    Centralises the conservative stop so every blocking path behaves identically:
    no record(), browser closed, reason captured on the job.
    """
    try:
        artifacts.stage(stage, note=reason, html=True)
    except Exception:
        pass
    job.needs_human_reason = reason
    job.advance(JobStatus.NEEDS_HUMAN, note=reason)
    store.save(job)
    try:
        controller.close()
    except Exception:
        pass
    return GenerationOutcome(
        status=STATUS_NEEDS_HUMAN, job_id=job.id, reason=reason
    )


def _resolve_url(job: Job) -> str:
    """Map the job target to its configured URL ('' if unset)."""
    if (job.target or "").strip().lower() == "gemini":
        return config.gemini_url()
    return config.flow_url()


def _locator_has_value(locator: Any) -> bool:
    """Best-effort check that a prompt-box locator now holds some text."""
    for getter in ("input_value", "text_content"):
        try:
            value = getattr(locator, getter)()
        except Exception:
            continue
        if value and str(value).strip():
            return True
    return False


def _fill_prompt(locator: Any, prompt: str) -> bool:
    """Paste ``prompt`` into a located prompt box. True if it appears to stick."""
    filled = False
    for method in ("fill", "type"):
        fn = getattr(locator, method, None)
        if fn is None:
            continue
        try:
            fn(prompt)
            filled = True
            break
        except Exception:
            continue
    return filled


def _click(locator: Any) -> bool:
    """Best-effort click of a located control. True on success."""
    fn = getattr(locator, "click", None)
    if fn is None:
        return False
    try:
        fn()
        return True
    except Exception:
        return False


def generate_in_browser(
    job: Job,
    store: JobStore,
    *,
    controller: Any | None = None,
    rate_limiter: Any | None = None,
    selectors_config: dict[str, Any] | None = None,
    artifacts: Any | None = None,
    poll_timeout_s: int = 600,
    poll_interval_s: int = 5,
) -> GenerationOutcome:
    """Run ONE conservative browser generation for ``job`` and continue the pipeline.

    See the module docstring for the full safety contract.  Returns a
    :class:`GenerationOutcome`; never raises for expected blocking situations.
    """
    # Lazy default wiring (kept out of the signature so tests inject fakes).
    if rate_limiter is None:
        from social_video_factory.rate_limit import RateLimiter

        rate_limiter = RateLimiter()
    if selectors_config is None:
        selectors_config = load_selector_config()

    # 1. RATE-LIMIT GATE FIRST — before the browser is ever opened.
    decision = rate_limiter.check()
    if not decision.allowed:
        reason = f"rate limited: {decision.reason}"
        job.advance(JobStatus.GENERATING, note=reason)
        store.save(job)
        return GenerationOutcome(
            status=STATUS_RATE_LIMITED, job_id=job.id, reason=decision.reason
        )
    if decision.needs_human_confirm:
        confirm: Callable[[str], bool] = getattr(rate_limiter, "confirm", lambda _m: True)
        if not confirm(
            f"Human confirmation due before generation #{job.id}. Proceed? [y/N]: "
        ):
            # Consistency with every other needs_human exit: persist the reason
            # and advance to NEEDS_HUMAN (the browser was never opened, so there
            # is nothing to close/record — unlike _needs_human's full path).
            reason = "human confirm declined"
            job.needs_human_reason = reason
            job.advance(JobStatus.NEEDS_HUMAN, note=reason)
            store.save(job)
            return GenerationOutcome(
                status=STATUS_NEEDS_HUMAN, job_id=job.id, reason=reason
            )

    # 2. Resolve the target URL (browser still not opened).
    url = _resolve_url(job)
    if not url:
        reason = (
            f"no URL configured for target {job.target!r}; "
            "set SOCIAL_FACTORY_FLOW_URL / SOCIAL_FACTORY_GEMINI_URL"
        )
        job.error = reason
        job.advance(JobStatus.FAILED, note=reason)
        store.save(job)
        return GenerationOutcome(status=STATUS_ERROR, job_id=job.id, reason=reason)

    # Now wire the controller + artifacts (opening the browser happens below).
    if controller is None:
        from social_video_factory.browser.controller import get_controller

        controller = get_controller()
    if artifacts is None:
        from social_video_factory.browser.artifacts import ArtifactLogger

        artifacts = ArtifactLogger(job.id, controller)

    try:
        # 3. Open the browser + navigate.
        controller.start()
        controller.goto(url)
        artifacts.stage("opened", note=f"navigated to target={job.target}")

        # 4. Hard-stop check immediately after navigation.
        hit = detect_hard_stop(_page_text(controller), selectors_config)
        if hit:
            return _needs_human(
                job, store, controller, artifacts, f"hard stop detected: {hit}"
            )

        resolver = SelectorResolver(
            controller.page, selectors_config, job.target, controller
        )

        flow_prepared = None
        if (job.target or "").strip().lower() == "flow":
            try:
                flow_prepared = flow_ui.prepare_generation(
                    controller.page,
                    url,
                    job.prompt or "",
                )
                prompt_box = flow_prepared.prompt_box
            except flow_ui.FlowUIError as exc:
                resolver.manual_pause(str(exc))
                return _needs_human(
                    job,
                    store,
                    controller,
                    artifacts,
                    f"Flow UI needs manual action: {exc}",
                    stage="flow_ui",
                )
        else:
            # Gemini and user overrides retain the generic layered resolver.
            prompt_box = resolver.locate("prompt_box")
            if prompt_box is None or not _fill_prompt(prompt_box, job.prompt or ""):
                resolver.manual_pause(
                    "could not paste the prompt automatically; paste this prompt "
                    f"into the box and start generation:\n{job.prompt}"
                )
        artifacts.stage(
            "prompt_pasted",
            selector_used="prompt_box" if prompt_box is not None else "manual",
        )

        # 6. Submit only if the UI looks ready: the submit control must exist
        #    and (when we filled it) the prompt box should now hold content.
        #    A missing prompt box just means we paused for a human above.
        submit = (
            flow_prepared.submit
            if flow_prepared is not None
            else resolver.locate("submit")
        )
        prompt_present = prompt_box is None or _locator_has_value(prompt_box)
        if submit is None or not prompt_present or not _click(submit):
            resolver.manual_pause(
                "could not submit automatically; press the generate/submit "
                "control in the open browser window"
            )
        artifacts.stage(
            "submitted",
            selector_used="submit" if submit is not None else "manual",
        )

        # Re-check hard stops right after submit.
        hit = detect_hard_stop(_page_text(controller), selectors_config)
        if hit:
            return _needs_human(
                job, store, controller, artifacts, f"hard stop detected: {hit}"
            )

        # 7. Wait for generation — re-check hard stops every iteration.
        deadline = time.monotonic() + poll_timeout_s
        completed = False
        flow_edit_url: str | None = None
        while time.monotonic() < deadline:
            hit = detect_hard_stop(_page_text(controller), selectors_config)
            if hit:
                return _needs_human(
                    job,
                    store,
                    controller,
                    artifacts,
                    f"hard stop appeared during generation: {hit}",
                )
            if flow_prepared is not None:
                flow_edit_url = flow_ui.new_result_edit_url(
                    controller.page,
                    flow_prepared.baseline_video_count,
                )
                if flow_edit_url is not None:
                    completed = True
                    break
            else:
                # Indicator absence is not completion: some UIs expose no
                # progress element. Require an actual result.
                result = resolver.locate("result_video")
                if result is not None:
                    completed = True
                    break
            time.sleep(poll_interval_s)

        if not completed:
            resolver.manual_pause(
                "generation is taking too long; complete it (and download the "
                "clip if needed) manually in the open browser window"
            )
        artifacts.stage("generation_done", note="completed" if completed else "manual")

        # 8. Download / export — prefer MP4 if a format choice appears.
        downloaded: Path | None = None
        download_ctl: Any | None = None
        if flow_prepared is not None:
            if flow_edit_url is not None:
                try:
                    downloaded = flow_ui.download_from_detail(
                        controller,
                        flow_edit_url,
                    )
                    download_ctl = "flow_detail"
                except flow_ui.FlowUIError:
                    downloaded = None
        else:
            download_ctl = resolver.locate("download")

        if downloaded is None and download_ctl is not None and download_ctl != "flow_detail":
            def _trigger() -> None:
                _click(download_ctl)
                export = resolver.locate("export_mp4")
                if export is not None:
                    _click(export)

            try:
                downloaded = controller.expect_download(trigger=_trigger)
            except Exception:
                downloaded = None

        if downloaded is None:
            resolver.manual_pause(
                "could not capture the download automatically; download the "
                "finished clip (prefer MP4) in the open browser window"
            )
            downloaded = media.find_latest_download(config.downloads_dir())
        artifacts.stage(
            "downloaded",
            selector_used="download" if download_ctl is not None else "manual",
            note=str(downloaded) if downloaded else "no file captured",
        )

        # 9. Verify we actually have a video.
        if downloaded is None or not media.is_video_file(downloaded):
            return _needs_human(
                job, store, controller, artifacts, "no video download found"
            )

        # 10. Record the generation against the local budget; set raw path.
        rate_limiter.record()
        job.raw_media_path = str(downloaded)
        store.save(job)

        # Close the browser before the (CPU/IO-bound) pipeline stages run.
        try:
            controller.close()
        except Exception:
            pass

        # 11. Continue via the Phase-1 pipeline stages (no auto-publish): import
        #     then the shared review -> render -> captions -> approval tail.
        pipeline.run_import(job, store, src_path=downloaded)
        pipeline.finish_after_import(job, store)

        return GenerationOutcome(
            status=STATUS_SUCCESS, job_id=job.id, downloaded_path=str(downloaded)
        )

    except Exception as exc:  # unexpected failure
        try:
            artifacts.stage("error", note=f"unexpected error: {exc}", html=True)
        except Exception:
            pass
        reason = str(exc)
        job.error = reason
        job.advance(JobStatus.FAILED, note=f"unexpected error: {reason}")
        store.save(job)
        return GenerationOutcome(status=STATUS_ERROR, job_id=job.id, reason=reason)
    finally:
        # Always tear the browser down; close() is idempotent.
        try:
            controller.close()
        except Exception:
            pass
