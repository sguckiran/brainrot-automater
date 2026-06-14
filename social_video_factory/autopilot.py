"""One unattended autopilot pass: top up the queue, generate, summarize, alert.

This is the single unit a scheduler (systemd timer / Hermes cron) invokes on a
cadence. It is deliberately ONE pass (not an infinite loop) so the scheduler
owns timing, restarts, and reboots.

A pass:
  1. Tops up pending ``browser_flow`` work from the configured topic rotation
     (only if below ``target_pending`` — never floods the queue).
  2. Runs the conservative browser queue for up to ``per_run_limit`` jobs
     (generate -> import -> review -> render -> captions -> auto-publish, all
     already wired in the queue/pipeline; auto-publish stays gated on config).
  3. Builds a concise text summary.
  4. Pushes a Telegram/Discord alert if anything needs a human (needs_human /
     error) so the user knows to step in.

Everything external (store, the per-job ``generate`` callable, the ``notifier``)
is injectable so the whole pass is unit-testable with fakes and no real browser.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from social_video_factory import config, pipeline, topics
from social_video_factory.browser import queue as queue_mod
from social_video_factory.browser.worker import GenerationOutcome
from social_video_factory.models import GenerationMode
from social_video_factory.store import JobStore

logger = logging.getLogger(__name__)

# Outcome statuses that mean a human must intervene (worth a push alert).
_ALERT_STATUSES = {"needs_human", "error"}


@dataclass
class AutopilotResult:
    """Summary of one autopilot pass."""

    enqueued: int = 0
    processed: int = 0
    stopped_reason: str | None = None
    outcomes: list[GenerationOutcome] = field(default_factory=list)
    alerted: bool = False
    summary: str = ""


def _count_pending(store: JobStore) -> int:
    jobs = store.list_jobs(generation_mode=GenerationMode.BROWSER_FLOW.value)
    return sum(1 for j in jobs if j.status in queue_mod.PENDING_STATUSES)


def _top_up(store: JobStore, target_pending: int) -> int:
    """Enqueue new browser_flow jobs from the topic rotation up to the target.

    Returns how many were enqueued (0 when already at target or no topics
    configured).
    """
    deficit = target_pending - _count_pending(store)
    if deficit <= 0:
        return 0
    pairs = topics.next_topics(deficit)
    for template, topic in pairs:
        # generate_one(browser_flow) creates the job and runs idea->script->
        # prompt->save, then stops at `prompted` for the queue to pick up.
        pipeline.generate_one(
            template=template,
            topic=topic,
            generation_mode=GenerationMode.BROWSER_FLOW.value,
            store=store,
        )
    return len(pairs)


def _build_summary(result: AutopilotResult, store: JobStore) -> str:
    lines = [
        "social_video_factory autopilot pass",
        f"enqueued: {result.enqueued} | processed: {result.processed}",
    ]
    if result.stopped_reason:
        lines.append(f"stopped: {result.stopped_reason}")
    for outcome in result.outcomes:
        detail = f"  - {outcome.job_id}: {outcome.status}"
        if outcome.reason:
            detail += f" ({outcome.reason})"
        # Surface per-platform publish results when the job reached publishing.
        try:
            job = store.load(outcome.job_id)
            if job.publish_results:
                pub = ", ".join(
                    f"{p}={r.get('status', '?')}"
                    for p, r in job.publish_results.items()
                )
                detail += f" [publish: {pub}]"
        except Exception:
            pass
        lines.append(detail)
    if result.processed == 0 and result.enqueued == 0:
        lines.append("  (nothing to do — no pending jobs and no topics configured)")
    return "\n".join(lines)


def run_once(
    *,
    target_pending: int | None = None,
    per_run_limit: int | None = None,
    store: JobStore | None = None,
    generate: Callable[..., GenerationOutcome] | None = None,
    notifier: Callable[[str], Any] | None = None,
) -> AutopilotResult:
    """Run one autopilot pass. Never raises for expected outcomes.

    Args:
        target_pending: keep this many pending browser_flow jobs queued
            (defaults to ``config.autopilot_target_pending()``).
        per_run_limit: generate at most this many jobs this pass
            (defaults to ``config.autopilot_per_run_limit()``).
        store: job store (defaults to a fresh :class:`JobStore`).
        generate: per-job worker callable (defaults to the real browser worker
            via ``run_queue``; injected as a fake in tests).
        notifier: ``callable(text) -> Any`` used to push alerts (defaults to
            :func:`social_video_factory.notify.notify`).
    """
    store = store or JobStore()
    if target_pending is None:
        target_pending = config.autopilot_target_pending()
    if per_run_limit is None:
        per_run_limit = config.autopilot_per_run_limit()
    if notifier is None:
        from social_video_factory.notify import notify as notifier  # type: ignore[assignment]

    result = AutopilotResult()
    result.enqueued = _top_up(store, target_pending)

    queue_result = queue_mod.run_queue(
        limit=per_run_limit, store=store, generate=generate
    )
    result.processed = queue_result.processed
    result.outcomes = queue_result.outcomes
    result.stopped_reason = queue_result.stopped_reason
    result.summary = _build_summary(result, store)

    # Alert if any job needs a human.
    stalls = [o for o in result.outcomes if o.status in _ALERT_STATUSES]
    if stalls:
        stall_lines = "\n".join(
            f"  - {o.job_id}: {o.status} ({o.reason or 'see logs'})" for o in stalls
        )
        message = (
            "🟡 social_video_factory needs you\n"
            f"{len(stalls)} job(s) stopped for a human:\n{stall_lines}\n"
            "Action: VNC into the VM and resolve (e.g. re-login), then it resumes."
        )
        try:
            result.alerted = bool(notifier(message))
        except Exception as exc:  # notifications are advisory, never fatal
            logger.warning("autopilot notify failed: %s", type(exc).__name__)

    logger.info(result.summary)
    return result
