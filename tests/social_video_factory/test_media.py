"""media.find_latest_download ordering + import graceful-probe path."""

from __future__ import annotations

import os

import pytest

from social_video_factory import media
from social_video_factory.models import Job


@pytest.fixture(autouse=True)
def _tmp_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SOCIAL_FACTORY_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def _touch(path, mtime):
    path.write_bytes(b"\x00")
    os.utime(path, (mtime, mtime))


def test_find_latest_download_picks_newest(tmp_path):
    d = tmp_path / "dl"
    d.mkdir()
    older = d / "a.mp4"
    newer = d / "b.mov"
    _touch(older, mtime=1000)
    _touch(newer, mtime=2000)
    # A non-video file should be ignored even if newest.
    _touch(d / "notes.txt", mtime=3000)

    assert media.find_latest_download(d) == newer


def test_find_latest_download_empty_or_missing(tmp_path):
    assert media.find_latest_download(tmp_path / "nope") is None
    empty = tmp_path / "empty"
    empty.mkdir()
    assert media.find_latest_download(empty) is None


def test_import_generated_without_ffprobe_degrades(tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"\x00\x00\x00\x18ftyp")
    job = Job(template="dancing_cat")

    dest = media.import_generated(job, src)

    assert dest.exists()
    assert dest.name == f"SVF_{job.id}_dancing_cat_raw.mp4"
    assert job.imported_media_path == str(dest)
    # Sidecar exists and records probe availability gracefully.
    assert job.sidecar_path is not None
    import json

    with open(job.sidecar_path, encoding="utf-8") as fh:
        sidecar = json.load(fh)
    assert sidecar["job_id"] == job.id
    # ffprobe is not installed in this env, so the probe degrades.
    assert sidecar["probe_available"] is False
    assert "probe_error" in sidecar


def test_import_rejects_non_video(tmp_path):
    bad = tmp_path / "doc.txt"
    bad.write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError):
        media.import_generated(Job(), bad)
