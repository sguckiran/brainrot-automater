"""Queue runner against FAKES — no real browser / Playwright / network.

Covers the behaviours the Phase-4 brief requires:
  * selects ONLY pending browser_flow jobs (ignores mock jobs, other modes,
    and awaiting_approval / needs_human / failed ones);
  * respects ``limit`` and processes oldest-first;
  * all-success run -> processed == min(limit, pending), sleep between successes
    (count == processed - 1), stopped_reason is None;
  * needs_human on the 2nd job -> STOPS (3rd not processed), stopped_reason set,
    two outcomes recorded;
  * rate_limited -> stops;
  * a job with no prompt gets prepared (prompt populated) before generate runs.
"""

from __future__ import annotations

import pytest

from social_video_factory.browser import queue as queue_mod
from social_video_factory.browser.queue import run_queue
from social_video_factory.browser.worker import GenerationOutcome
from social_video_factory.models import GenerationMode, Job, JobStatus
from social_video_factory.store import JobStore


@pytest.fixture(autouse=True)
def _tmp_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SOCIAL_FACTORY_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def _make_job(
    *,
    status=JobStatus.PROMPTED.value,
    generation_mode=GenerationMode.BROWSER_FLOW.value,
    created_at,
    prompt="a prompt",
):
    job = Job(
        template="dancing_cat",
        topic="orange cat disco",
        generation_mode=generation_mode,
        target="flow",
        prompt=prompt,
        status=status,
        created_at=created_at,
    )
    return job


class FakeGenerate:
    """Injectable fake worker. Returns canned statuses per call, records jobs."""

    def __init__(self, statuses):
        self._statuses = list(statuses)
        self.calls: list[str] = []

    def __call__(self, job, store):
        self.calls.append(job.id)
        status = self._statuses.pop(0) if self._statuses else "success"
        return GenerationOutcome(status=status, job_id=job.id, reason=f"{status}-reason")


def test_selects_only_pending_browser_flow_oldest_first(monkeypatch):
    store = JobStore()
    # Eligible, varying created_at (out of order on disk).
    a = _make_job(created_at="2026-01-03T00:00:00Z")
    b = _make_job(created_at="2026-01-01T00:00:00Z", status=JobStatus.CREATED.value)
    c = _make_job(created_at="2026-01-02T00:00:00Z", status=JobStatus.IDEA.value)
    # Ineligible ones that must be ignored.
    mock_job = _make_job(
        created_at="2026-01-01T00:00:00Z",
        generation_mode=GenerationMode.MOCK.value,
    )
    awaiting = _make_job(
        created_at="2026-01-01T00:00:00Z", status=JobStatus.AWAITING_APPROVAL.value
    )
    needs_human = _make_job(
        created_at="2026-01-01T00:00:00Z", status=JobStatus.NEEDS_HUMAN.value
    )
    failed = _make_job(
        created_at="2026-01-01T00:00:00Z", status=JobStatus.FAILED.value
    )
    other_mode = _make_job(
        created_at="2026-01-01T00:00:00Z",
        generation_mode=GenerationMode.ASSISTED_FLOW.value,
    )
    for j in (a, b, c, mock_job, awaiting, needs_human, failed, other_mode):
        store.save(j)

    fake = FakeGenerate(["success", "success", "success"])
    result = run_queue(
        limit=5, store=store, sleep=lambda _s: None, pause_seconds=0, generate=fake
    )

    # Only the three eligible jobs, oldest-first: b, c, a.
    assert fake.calls == [b.id, c.id, a.id]
    assert result.processed == 3
    assert result.stopped_reason is None


def test_all_success_respects_limit_and_sleeps_between(monkeypatch):
    store = JobStore()
    for i in range(5):
        store.save(_make_job(created_at=f"2026-01-0{i + 1}T00:00:00Z"))

    sleeps: list[float] = []
    fake = FakeGenerate(["success"] * 5)
    result = run_queue(
        limit=3,
        store=store,
        sleep=lambda s: sleeps.append(s),
        pause_seconds=42,
        generate=fake,
    )

    assert result.processed == 3  # min(limit=3, pending=5)
    assert result.stopped_reason is None
    # sleep called between successes: processed - 1 == 2 times, with pause value.
    assert sleeps == [42, 42]


def test_needs_human_on_second_job_stops_queue(monkeypatch):
    store = JobStore()
    j1 = _make_job(created_at="2026-01-01T00:00:00Z")
    j2 = _make_job(created_at="2026-01-02T00:00:00Z")
    j3 = _make_job(created_at="2026-01-03T00:00:00Z")
    for j in (j1, j2, j3):
        store.save(j)

    fake = FakeGenerate(["success", "needs_human", "success"])
    result = run_queue(
        limit=5, store=store, sleep=lambda _s: None, pause_seconds=0, generate=fake
    )

    # Third job never processed.
    assert fake.calls == [j1.id, j2.id]
    assert result.processed == 2
    assert len(result.outcomes) == 2
    assert result.stopped_reason is not None
    assert "needs_human" in result.stopped_reason


def test_rate_limited_stops_queue(monkeypatch):
    store = JobStore()
    j1 = _make_job(created_at="2026-01-01T00:00:00Z")
    j2 = _make_job(created_at="2026-01-02T00:00:00Z")
    for j in (j1, j2):
        store.save(j)

    fake = FakeGenerate(["rate_limited", "success"])
    result = run_queue(
        limit=5, store=store, sleep=lambda _s: None, pause_seconds=0, generate=fake
    )

    assert fake.calls == [j1.id]
    assert result.processed == 1
    assert result.stopped_reason is not None
    assert "rate_limited" in result.stopped_reason


def test_error_stops_queue(monkeypatch):
    store = JobStore()
    j1 = _make_job(created_at="2026-01-01T00:00:00Z")
    j2 = _make_job(created_at="2026-01-02T00:00:00Z")
    for j in (j1, j2):
        store.save(j)

    fake = FakeGenerate(["error", "success"])
    result = run_queue(
        limit=5, store=store, sleep=lambda _s: None, pause_seconds=0, generate=fake
    )

    assert fake.calls == [j1.id]
    assert result.processed == 1
    assert result.stopped_reason is not None
    assert "error" in result.stopped_reason


def test_job_without_prompt_is_prepared_before_generate(monkeypatch):
    store = JobStore()
    bare = _make_job(
        created_at="2026-01-01T00:00:00Z",
        status=JobStatus.CREATED.value,
        prompt="",
    )
    store.save(bare)

    seen_prompt = {}

    def generate(job, store):
        seen_prompt["prompt"] = job.prompt
        return GenerationOutcome(status="success", job_id=job.id)

    result = run_queue(
        limit=5, store=store, sleep=lambda _s: None, pause_seconds=0, generate=generate
    )

    assert result.processed == 1
    # The job was prepared: a prompt was populated before generate ran.
    assert seen_prompt["prompt"]
    # And persisted.
    reloaded = JobStore().load(bare.id)
    assert reloaded.prompt
