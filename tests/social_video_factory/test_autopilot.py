"""Autopilot pass orchestration — fakes only, no real browser/network/sleep."""

from __future__ import annotations

import pytest

from social_video_factory import autopilot as autopilot_mod
from social_video_factory import config
from social_video_factory.autopilot import run_once
from social_video_factory.browser import queue as queue_mod
from social_video_factory.browser.worker import GenerationOutcome
from social_video_factory.store import JobStore


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("SOCIAL_FACTORY_DATA_DIR", str(tmp_path / "data"))
    # Neutralize run_queue's inter-success pause so tests don't sleep 180s.
    real_run_queue = queue_mod.run_queue
    monkeypatch.setattr(
        autopilot_mod.queue_mod,
        "run_queue",
        lambda **kw: real_run_queue(sleep=lambda _s: None, **kw),
    )
    # Default topic rotation for tests that enqueue.
    monkeypatch.setattr(config, "autopilot_topics", lambda: ["a", "b", "c", "d"])
    monkeypatch.setattr(config, "autopilot_templates", lambda: ["t1"])
    return tmp_path


def _success(job, store):
    return GenerationOutcome(status="success", job_id=job.id, downloaded_path="x.mp4")


def _needs_human(job, store):
    return GenerationOutcome(status="needs_human", job_id=job.id, reason="login required")


def test_tops_up_to_target_then_processes():
    notes: list[str] = []
    result = run_once(
        target_pending=2,
        per_run_limit=2,
        generate=_success,
        notifier=lambda text: notes.append(text) or True,
    )
    assert result.enqueued == 2  # started empty, topped up to target
    assert result.processed == 2
    assert all(o.status == "success" for o in result.outcomes)
    assert result.alerted is False
    assert notes == []  # no alert on all-success
    assert "enqueued: 2" in result.summary


def test_does_not_enqueue_when_already_at_target():
    store = JobStore()
    # Pre-seed 2 pending browser_flow jobs.
    from social_video_factory import pipeline
    from social_video_factory.models import GenerationMode

    for topic in ("x", "y"):
        pipeline.generate_one(
            template="t1", topic=topic,
            generation_mode=GenerationMode.BROWSER_FLOW.value, store=store,
        )

    result = run_once(
        target_pending=2, per_run_limit=2, store=store,
        generate=_success, notifier=lambda t: True,
    )
    assert result.enqueued == 0  # already at target


def test_alerts_on_needs_human():
    notes: list[str] = []
    result = run_once(
        target_pending=2, per_run_limit=2,
        generate=_needs_human,
        notifier=lambda text: notes.append(text) or True,
    )
    # run_queue stops on the first needs_human.
    assert result.processed == 1
    assert result.stopped_reason and "needs_human" in result.stopped_reason
    assert result.alerted is True
    assert len(notes) == 1
    assert "needs you" in notes[0]
    assert result.outcomes[0].job_id in notes[0]


def test_nothing_to_do_when_no_topics(monkeypatch):
    monkeypatch.setattr(config, "autopilot_topics", lambda: [])
    notes: list[str] = []
    result = run_once(
        target_pending=3, per_run_limit=2,
        generate=_success, notifier=lambda t: notes.append(t) or True,
    )
    assert result.enqueued == 0
    assert result.processed == 0
    assert "nothing to do" in result.summary
    assert notes == []


def test_default_notifier_is_used_when_none(monkeypatch):
    # When notifier is None, run_once imports the real notify.notify; with no
    # creds configured it is a quiet no-op (alerted False), never raising.
    result = run_once(target_pending=1, per_run_limit=1, generate=_needs_human)
    assert result.processed == 1
    assert result.alerted is False  # no Telegram/Discord creds in the test env
