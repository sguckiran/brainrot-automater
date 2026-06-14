"""Mock pipeline E2E — must reach awaiting_approval without ffmpeg/ffprobe."""

from __future__ import annotations

import shutil

import pytest

from social_video_factory.models import GenerationMode, JobStatus
from social_video_factory.pipeline import generate_one
from social_video_factory.store import JobStore


@pytest.fixture(autouse=True)
def _tmp_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SOCIAL_FACTORY_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def test_mock_pipeline_reaches_awaiting_approval():
    job = generate_one(
        template="dancing_cat",
        topic="orange cat disco kitchen",
        generation_mode="mock",
    )

    assert job.status == JobStatus.AWAITING_APPROVAL.value
    # Review accepted (mock backend).
    assert job.review.get("accepted") is True
    assert job.review.get("backend") == "mock"
    # Captions present for both platforms.
    assert set(job.captions) == {"tiktok", "instagram"}
    assert job.captions["tiktok"]
    assert job.captions["instagram"]
    # Creative stages populated.
    assert job.idea and job.script and job.prompt
    assert job.prompt_path is not None
    # Media imported even without ffprobe.
    assert job.imported_media_path is not None
    # The job persisted and reloads identically.
    reloaded = JobStore().load(job.id)
    assert reloaded.status == JobStatus.AWAITING_APPROVAL.value


@pytest.mark.skipif(
    shutil.which("ffmpeg") is not None,
    reason="asserts the graceful skip path that only happens when ffmpeg is absent",
)
def test_mock_render_skipped_gracefully_without_ffmpeg():
    # ffmpeg is not installed in the dev env, so render is skipped, not crashed.
    job = generate_one("t", "x", generation_mode="mock")
    render_notes = [
        h["note"] for h in job.history if h["status"] == JobStatus.RENDERED.value
    ]
    assert render_notes
    # Either skipped (no ffmpeg) or an actual path; in this env it's skipped.
    assert job.rendered_path is None
    assert any("render skipped" in n for n in render_notes)


def test_history_records_all_stages():
    job = generate_one("t", "x", generation_mode="mock")
    statuses = [h["status"] for h in job.history]
    for expected in (
        JobStatus.CREATED.value,
        JobStatus.IDEA.value,
        JobStatus.SCRIPTED.value,
        JobStatus.PROMPTED.value,
        JobStatus.IMPORTED.value,
        JobStatus.PROBED.value,
        JobStatus.ACCEPTED.value,
        JobStatus.RENDERED.value,
        JobStatus.CAPTIONED.value,
        JobStatus.AWAITING_APPROVAL.value,
    ):
        assert expected in statuses, expected


def test_prompt_only_modes_stop_after_prompt():
    job = generate_one("t", "x", generation_mode="browser_flow")
    assert job.status == JobStatus.PROMPTED.value
    assert job.prompt_path is not None
    assert job.imported_media_path is None
    assert job.captions == {}


def test_api_veo_disabled():
    with pytest.raises(RuntimeError, match="api_veo is disabled"):
        generate_one("t", "x", generation_mode=GenerationMode.API_VEO.value)
