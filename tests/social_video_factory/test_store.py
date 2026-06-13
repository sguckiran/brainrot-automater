"""JobStore save/load/list/exists under a tmp data dir."""

from __future__ import annotations

import json

import pytest

from social_video_factory.models import Job, JobStatus
from social_video_factory.store import JobStore


@pytest.fixture(autouse=True)
def _tmp_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SOCIAL_FACTORY_DATA_DIR", str(tmp_path))
    return tmp_path


def test_save_then_load_roundtrip():
    store = JobStore()
    job = Job(template="t", topic="x")
    job.advance(JobStatus.IDEA)
    path = store.save(job)

    assert path.exists()
    loaded = store.load(job.id)
    assert loaded.to_dict() == job.to_dict()


def test_save_is_atomic_valid_json(_tmp_data_dir):
    store = JobStore()
    job = Job()
    path = store.save(job)
    # File is valid JSON and no stray temp files remain in the dir.
    with path.open(encoding="utf-8") as fh:
        json.load(fh)
    leftovers = [p for p in path.parent.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_exists():
    store = JobStore()
    job = Job()
    assert store.exists(job.id) is False
    store.save(job)
    assert store.exists(job.id) is True


def test_list_jobs_filters_and_ordering():
    store = JobStore()
    a = Job(generation_mode="mock")
    a.advance(JobStatus.AWAITING_APPROVAL)
    b = Job(generation_mode="browser_flow")
    b.advance(JobStatus.PROMPTED)
    # Force distinct created_at ordering.
    a.created_at = "2026-01-01T00:00:00Z"
    b.created_at = "2026-02-01T00:00:00Z"
    store.save(a)
    store.save(b)

    all_jobs = store.list_jobs()
    assert [j.id for j in all_jobs] == [b.id, a.id]  # newest first

    by_status = store.list_jobs(status="awaiting_approval")
    assert [j.id for j in by_status] == [a.id]

    by_mode = store.list_jobs(generation_mode="browser_flow")
    assert [j.id for j in by_mode] == [b.id]


def test_load_missing_raises():
    with pytest.raises(FileNotFoundError):
        JobStore().load("does-not-exist")
