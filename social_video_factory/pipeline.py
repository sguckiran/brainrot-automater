"""Pipeline orchestration — wire the creative/media/render stages per mode.

WHY this layer exists: each stage (idea, script, prompt, import, review, render,
captions, approval) must (1) do its work, (2) record a status transition via
``Job.advance`` so the history is a complete audit trail, and (3) persist the
job so a crash leaves a resumable on-disk record. Centralising that
advance+persist discipline here keeps the individual stage modules pure and
keeps every mode consistent.

Modes (see the master plan):
- ``mock``: synthesize a clip locally (ffmpeg ``testsrc`` if available, else a
  tiny placeholder ``.mp4``), then run import -> review -> render -> captions ->
  ``awaiting_approval``. When ffmpeg is absent the render encode is SKIPPED
  (``rendered_path=None`` + a history note) so the E2E still completes. NEVER
  auto-publishes.
- ``browser_flow`` / ``assisted_flow`` / ``flow_import``: run the creative
  stages and save the prompt to a file, then STOP with a message telling the
  user to run the (later-phase) browser command.
- ``api_veo``: disabled in this build — raises a clear error.

This module is deliberately free of ``agent/`` and ``tools/`` imports.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from social_video_factory import (
    captions as captions_mod,
    config,
    ideas,
    media,
    prompt_build,
    render as render_mod,
    review as review_mod,
    script as script_mod,
)
from social_video_factory.models import (
    PROVIDER_GEMINI_OMNI_BROWSER,
    PROVIDER_GOOGLE_FLOW_BROWSER,
    GenerationMode,
    Job,
    JobStatus,
)
from social_video_factory.store import JobStore

# Modes that stop after saving the prompt (the browser/manual phases pick up
# from the saved prompt file in a later phase).
_PROMPT_ONLY_MODES = {
    GenerationMode.BROWSER_FLOW.value,
    GenerationMode.ASSISTED_FLOW.value,
    GenerationMode.FLOW_IMPORT.value,
}

# Smallest plausible MP4 placeholder: an empty ftyp/mdat-less stub is enough for
# Phase 1 (no ffprobe in dev), since import only validates the extension and the
# probe degrades gracefully. We write a minimal ftyp box so the bytes at least
# look MP4-ish to casual inspection.
_PLACEHOLDER_MP4 = bytes.fromhex(
    "00000018667479706973636f6d0000020069736f6d69736f32"
)


def _provider_for_target(target: str) -> str:
    """Map a ``--target`` choice to a provider marker."""
    return (
        PROVIDER_GEMINI_OMNI_BROWSER
        if target.strip().lower() == "gemini"
        else PROVIDER_GOOGLE_FLOW_BROWSER
    )


def create_job(
    template: str,
    topic: str,
    generation_mode: str = GenerationMode.MOCK.value,
    target: str = "flow",
    store: JobStore | None = None,
) -> Job:
    """Create, persist, and return a new :class:`Job` in the ``created`` state."""
    store = store or JobStore()
    job = Job(
        template=template,
        topic=topic,
        generation_mode=generation_mode,
        target=target,
        provider=_provider_for_target(target),
    )
    job.advance(JobStatus.CREATED, note=f"created ({generation_mode}, target={target})")
    store.save(job)
    return job


# --- individual stages: each advances status + persists --------------------


def run_idea(job: Job, store: JobStore) -> Job:
    job.idea = ideas.build_idea(job.template, job.topic)
    job.advance(JobStatus.IDEA, note="idea generated")
    store.save(job)
    return job


def run_script(job: Job, store: JobStore) -> Job:
    job.script = script_mod.build_script(job.template, job.topic, job.idea)
    job.advance(JobStatus.SCRIPTED, note="script generated")
    store.save(job)
    return job


def run_prompt(job: Job, store: JobStore) -> Job:
    job.prompt = prompt_build.build_prompt(job.template, job.topic, job.idea, job.script)
    job.advance(JobStatus.PROMPTED, note="generation prompt built")
    store.save(job)
    return job


def save_prompt_file(job: Job, store: JobStore) -> Job:
    """Write the job's prompt to ``logs_dir()`` and record its path."""
    path = config.logs_dir() / f"SVF_{job.id}_prompt.txt"
    with path.open("w", encoding="utf-8") as fh:
        fh.write(job.prompt)
    job.prompt_path = str(path)
    job.advance(JobStatus.PROMPTED, note=f"prompt saved to {path}")
    store.save(job)
    return job


def _synthesize_mock_clip(job: Job) -> Path:
    """Produce a local source clip for mock mode.

    Uses ffmpeg ``testsrc`` when available; otherwise writes a tiny placeholder
    ``.mp4`` so the import/probe path runs without ffmpeg.
    """
    dest = config.downloads_dir() / f"SVF_{job.id}_mock_src.mp4"
    if shutil.which("ffmpeg"):
        command = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=4:size=720x1280:rate=30",
            "-pix_fmt",
            "yuv420p",
            str(dest),
        ]
        try:
            subprocess.run(command, capture_output=True, check=True)
            return dest
        except (subprocess.SubprocessError, OSError):
            # Fall through to the placeholder on any ffmpeg failure.
            pass
    with dest.open("wb") as fh:
        fh.write(_PLACEHOLDER_MP4)
    return dest


def run_import(job: Job, store: JobStore, src_path: str | Path | None = None) -> Job:
    """Import a source clip (synthesizing one for mock mode if needed)."""
    if src_path is None:
        src_path = _synthesize_mock_clip(job)
    job.advance(JobStatus.GENERATING, note="source clip ready")
    media.import_generated(job, src_path)
    job.advance(JobStatus.IMPORTED, note=f"imported -> {job.imported_media_path}")
    # Surface probe availability in the history for visibility.
    note = "probe skipped: ffprobe unavailable" if not shutil.which("ffprobe") else "probed"
    job.advance(JobStatus.PROBED, note=note)
    store.save(job)
    return job


def run_review(job: Job, store: JobStore) -> Job:
    job.advance(JobStatus.REVIEWING, note="reviewing media")
    verdict = review_mod.review(job)
    job.review = verdict
    if verdict.get("accepted"):
        job.advance(JobStatus.ACCEPTED, note=f"review accepted ({verdict.get('backend')})")
    else:
        job.advance(JobStatus.REJECTED, note=str(verdict.get("reason")))
    store.save(job)
    return job


def run_render(job: Job, store: JobStore) -> Job:
    """Render the 9:16 output, skipping the encode gracefully if ffmpeg absent."""
    output = render_mod.render_9x16(job)
    if output is None:
        job.rendered_path = None
        if not shutil.which("ffmpeg"):
            job.advance(JobStatus.RENDERED, note="render skipped: ffmpeg unavailable")
        else:
            job.advance(
                JobStatus.RENDERED,
                note=f"render produced no output ({job.error or 'no input media'})",
            )
    else:
        job.advance(JobStatus.RENDERED, note=f"rendered -> {output}")
    store.save(job)
    return job


def run_captions(job: Job, store: JobStore) -> Job:
    job.captions = captions_mod.build_captions(job)
    job.advance(JobStatus.CAPTIONED, note="captions generated")
    store.save(job)
    return job


def finalize_approval(job: Job, store: JobStore) -> Job:
    """Move a fully-processed job to ``awaiting_approval``. Never auto-publishes."""
    job.advance(JobStatus.AWAITING_APPROVAL, note="awaiting human approval (no auto-publish)")
    store.save(job)
    return job


def finish_after_import(job: Job, store: JobStore) -> Job:
    """Run the post-import tail: review -> render -> captions -> approval.

    Shared by the browser worker (after it imports a downloaded clip) and the
    ``import-latest-browser-download`` manual-recovery path, so both reach
    ``awaiting_approval`` via exactly the same stages.  Never auto-publishes.
    """
    run_review(job, store)
    run_render(job, store)
    run_captions(job, store)
    finalize_approval(job, store)
    return job


def generate_one(
    template: str,
    topic: str,
    generation_mode: str = GenerationMode.MOCK.value,
    target: str = "flow",
    store: JobStore | None = None,
) -> Job:
    """Create a job and run it as far as the mode allows.

    - ``mock``: full pipeline to ``awaiting_approval``.
    - prompt-only modes: idea -> script -> prompt -> save prompt, then STOP.
    - ``api_veo``: raises (disabled in this build).
    """
    store = store or JobStore()

    if generation_mode == GenerationMode.API_VEO.value:
        raise RuntimeError(
            "api_veo is disabled in this build (no Veo/Gemini API billing). "
            "Use generation_mode='mock' or 'browser_flow'."
        )

    job = create_job(template, topic, generation_mode, target, store=store)
    run_idea(job, store)
    run_script(job, store)
    run_prompt(job, store)
    save_prompt_file(job, store)

    if generation_mode in _PROMPT_ONLY_MODES:
        print(
            f"Job {job.id} prepared in '{generation_mode}' mode. Prompt saved to "
            f"{job.prompt_path}. Run the browser generation command "
            f"(browser-generate --job-id {job.id}) in a later phase to continue."
        )
        return job

    if generation_mode != GenerationMode.MOCK.value:
        raise RuntimeError(f"unsupported generation_mode: {generation_mode!r}")

    # mock: continue through the full pipeline.
    run_import(job, store)
    run_review(job, store)
    run_render(job, store)
    run_captions(job, store)
    finalize_approval(job, store)
    return job
