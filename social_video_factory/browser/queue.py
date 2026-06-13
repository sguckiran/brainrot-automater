"""Sequential, conservative queue runner for ``browser_flow`` jobs.

This drives several prepared ``browser_flow`` jobs one-at-a-time through the
real browser worker (:func:`social_video_factory.browser.worker.generate_in_browser`),
pausing between successes so each generation clears the LOCAL min-gap, and
STOPPING immediately on any blocking outcome.

CONSERVATIVE BY DESIGN (mirrors the worker's safety contract):
  * Only PENDING ``browser_flow`` jobs are eligible — jobs that have been
    prepared (idea/script/prompt) but not yet generated, imported, failed,
    flagged ``needs_human``, or already awaiting approval are skipped.
  * On ``needs_human`` (a hard stop), ``error``, OR ``rate_limited`` the queue
    STOPS immediately and records why — there is no point continuing: a hard
    stop needs a human, and the rate-limit caps/min-gap will keep denying.
  * Between SUCCESSES we ``sleep(pause_seconds)`` so the next generation does
    not trip the local min-seconds-between-generations gate.
  * Nothing here bypasses login, usage limits, or safety; it merely sequences
    calls to the worker, which enforces all of that itself.

Everything external (the store, the ``generate`` callable, ``sleep``) is
injectable so the whole runner is unit-testable with FAKES and no real browser.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from social_video_factory import config, pipeline
from social_video_factory.browser.worker import (
    STATUS_SUCCESS,
    GenerationOutcome,
    generate_in_browser,
)
from social_video_factory.models import GenerationMode, JobStatus
from social_video_factory.store import JobStore

# Statuses that mean "prepared but not yet generated/imported" — i.e. a job the
# queue may still pick up.  Anything past this (generating/imported/...,
# awaiting_approval, needs_human, failed) is intentionally excluded.
PENDING_STATUSES = frozenset(
    {
        JobStatus.CREATED.value,
        JobStatus.IDEA.value,
        JobStatus.SCRIPTED.value,
        JobStatus.PROMPTED.value,
    }
)


@dataclass
class QueueResult:
    """Outcome of a :func:`run_queue` run.

    ``processed`` is how many jobs were actually handed to ``generate``;
    ``outcomes`` holds every :class:`GenerationOutcome` produced (in order),
    and ``stopped_reason`` is set when the queue stopped early on a blocking
    outcome (``None`` if it ran to the natural end of the eligible jobs).
    """

    processed: int = 0
    outcomes: list[GenerationOutcome] = field(default_factory=list)
    stopped_reason: str | None = None


def _select_pending(store: JobStore, limit: int) -> list:
    """Return up to ``limit`` pending ``browser_flow`` jobs, oldest-first."""
    jobs = store.list_jobs(generation_mode=GenerationMode.BROWSER_FLOW.value)
    pending = [j for j in jobs if j.status in PENDING_STATUSES]
    # Stable, deterministic oldest-first order (list_jobs returns newest-first).
    pending.sort(key=lambda j: j.created_at)
    return pending[:limit]


def _ensure_prompt(job, store: JobStore) -> None:
    """Prepare a job that has no prompt yet (idea -> script -> prompt -> save)."""
    if job.prompt:
        return
    pipeline.run_idea(job, store)
    pipeline.run_script(job, store)
    pipeline.run_prompt(job, store)
    pipeline.save_prompt_file(job, store)


def run_queue(
    limit: int = 5,
    *,
    store: JobStore | None = None,
    sleep: Callable[[float], Any] = time.sleep,
    pause_seconds: float | None = None,
    generate: Callable[..., GenerationOutcome] | None = None,
) -> QueueResult:
    """Process up to ``limit`` pending ``browser_flow`` jobs one-by-one.

    Pending jobs are selected oldest-first.  Each job is prepared (its prompt
    built if missing) and then handed to ``generate(job, store)``.  On success,
    if more work remains we ``sleep(pause_seconds)`` before the next job so the
    local min-gap is respected.  On ``needs_human`` / ``error`` / ``rate_limited``
    the queue stops immediately and records ``stopped_reason``.

    Args:
        limit: maximum number of jobs to process.
        store: job store (defaults to a fresh :class:`JobStore`).
        sleep: sleep callable (injected as a no-op in tests).
        pause_seconds: seconds to pause between successes (defaults to
            :func:`config.min_seconds_between_generations`).
        generate: the per-job worker callable (defaults to
            :func:`generate_in_browser`; injected as a fake in tests).

    Returns:
        A :class:`QueueResult`; all outcomes are recorded regardless of stop.
    """
    store = store or JobStore()
    if generate is None:
        generate = generate_in_browser
    if pause_seconds is None:
        pause_seconds = config.min_seconds_between_generations()

    pending = _select_pending(store, limit)
    result = QueueResult()

    for index, job in enumerate(pending):
        _ensure_prompt(job, store)
        outcome = generate(job, store)
        result.outcomes.append(outcome)
        result.processed += 1

        if outcome.status == STATUS_SUCCESS:
            # Pause before the next job (if any) so it clears the local min-gap.
            if index + 1 < len(pending):
                sleep(pause_seconds)
            continue

        # needs_human (hard stop), error, or rate_limited: STOP immediately.
        result.stopped_reason = (
            f"{outcome.status}: {outcome.reason}"
            if outcome.reason
            else outcome.status
        )
        break

    return result
