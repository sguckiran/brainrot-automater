"""``import-latest-browser-download`` manual-recovery path — no real browser.

Covers the Phase-4 brief:
  * with a video in the downloads dir -> imports + reaches awaiting_approval
    (ffmpeg absent -> render skipped gracefully); imported_media_path set;
  * empty downloads dir -> the CLI function raises SystemExit(5);
  * missing job -> SystemExit(2).
"""

from __future__ import annotations

import pytest

from social_video_factory import cli, config
from social_video_factory.models import GenerationMode, Job, JobStatus
from social_video_factory.store import JobStore


@pytest.fixture(autouse=True)
def _tmp_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SOCIAL_FACTORY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("SOCIAL_FACTORY_BROWSER_DOWNLOAD_DIR", raising=False)
    return tmp_path


def _make_job(store: JobStore) -> Job:
    job = Job(
        template="dancing_cat",
        topic="orange cat disco",
        generation_mode=GenerationMode.BROWSER_FLOW.value,
        target="flow",
        prompt="a dancing cat",
        status=JobStatus.PROMPTED.value,
    )
    store.save(job)
    return job


def test_import_latest_reaches_awaiting_approval():
    store = JobStore()
    job = _make_job(store)

    # Drop a video file in the configured downloads dir.
    clip = config.downloads_dir() / "result.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypisom")

    cli.import_latest_browser_download(job.id)

    reloaded = JobStore().load(job.id)
    assert reloaded.status == JobStatus.AWAITING_APPROVAL.value
    assert reloaded.imported_media_path is not None
    # ffmpeg absent in the dev env -> render skipped gracefully (no crash).
    assert reloaded.rendered_path is None
    # Captions produced by the shared tail.
    assert set(reloaded.captions) == {"tiktok", "instagram"}


def test_import_latest_empty_downloads_raises_systemexit_5():
    store = JobStore()
    job = _make_job(store)
    # downloads_dir() exists but is empty -> exit 5.
    config.downloads_dir()

    with pytest.raises(SystemExit) as exc:
        cli.import_latest_browser_download(job.id)
    assert exc.value.code == 5


def test_import_latest_missing_job_raises_systemexit_2():
    with pytest.raises(SystemExit) as exc:
        cli.import_latest_browser_download("does-not-exist")
    assert exc.value.code == 2
