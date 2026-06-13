"""Job JSON round-trip + advance() history."""

from __future__ import annotations

from social_video_factory.models import GenerationMode, Job, JobStatus


def test_job_to_from_dict_roundtrip():
    job = Job(template="dancing_cat", topic="disco kitchen")
    job.idea = "an idea"
    job.script = "line one\nline two"
    job.captions = {"tiktok": "t", "instagram": "i"}
    job.review = {"accepted": True}
    job.advance(JobStatus.IDEA, note="generated idea")

    data = job.to_dict()
    restored = Job.from_dict(data)

    assert restored.to_dict() == data
    assert restored.id == job.id
    assert restored.captions == {"tiktok": "t", "instagram": "i"}
    assert restored.history == job.history


def test_advance_appends_history_and_bumps_updated_at():
    job = Job()
    original_updated = job.updated_at
    assert job.history == []

    job.advance(JobStatus.IDEA, note="n1")
    job.advance("scripted", note="n2")

    assert job.status == "scripted"
    assert [h["status"] for h in job.history] == ["idea", "scripted"]
    assert [h["note"] for h in job.history] == ["n1", "n2"]
    assert all("ts" in h for h in job.history)
    assert job.updated_at >= original_updated


def test_from_dict_ignores_unknown_and_fills_defaults():
    restored = Job.from_dict({"id": "abc", "bogus_field": 123})
    assert restored.id == "abc"
    assert restored.generation_mode == GenerationMode.MOCK.value
    assert restored.history == []


def test_enums_are_str():
    assert JobStatus.AWAITING_APPROVAL == "awaiting_approval"
    assert GenerationMode.BROWSER_FLOW == "browser_flow"
