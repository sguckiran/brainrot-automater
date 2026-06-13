"""Media import + probe + sidecar.

WHY graceful degradation around ffprobe: this dev environment (and many CI
environments) do not have ffmpeg/ffprobe installed.  Import must still succeed —
it records ``probe_available=false`` / ``probe_error`` in the sidecar and
continues, rather than crashing the pipeline.  Probing is best-effort metadata,
not a gate.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from social_video_factory import config
from social_video_factory.models import Job

# Extensions we accept as "a video file".
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}


def is_video_file(path: str | Path) -> bool:
    """True if ``path`` has a recognised video extension (case-insensitive)."""
    return Path(path).suffix.lower() in VIDEO_EXTENSIONS


def find_latest_download(downloads_dir: str | Path) -> Path | None:
    """Return the newest video file in ``downloads_dir``, or ``None`` if none.

    Used by a later manual-recovery phase to pick up the most recent browser
    download.  Ordering is by modification time (newest first).
    """
    directory = Path(downloads_dir)
    if not directory.is_dir():
        return None
    candidates = [p for p in directory.iterdir() if p.is_file() and is_video_file(p)]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def probe_video(path: str | Path) -> dict[str, Any]:
    """Probe ``path`` with ffprobe, returning a metadata dict.

    Never raises: if ffprobe is missing or the probe fails, the returned dict
    has ``probe_available=False`` and a ``probe_error`` describing why.
    """
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {
            "probe_available": False,
            "probe_error": "ffprobe binary not found on PATH",
        }
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=True,
        )
        data = json.loads(result.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as exc:
        return {"probe_available": False, "probe_error": str(exc)}

    # Extract the convenient summary fields, tolerating missing keys.
    summary: dict[str, Any] = {"probe_available": True, "ffprobe_raw": data}
    fmt = data.get("format", {})
    summary["duration"] = fmt.get("duration")
    video_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
        None,
    )
    if video_stream:
        summary["codec"] = video_stream.get("codec_name")
        summary["width"] = video_stream.get("width")
        summary["height"] = video_stream.get("height")
        if summary.get("width") and summary.get("height"):
            summary["resolution"] = f"{summary['width']}x{summary['height']}"
    return summary


def import_generated(job: Job, src_path: str | Path) -> Path:
    """Import a generated clip for ``job``.

    Steps: validate extension -> probe (best-effort) -> copy into
    ``imported_dir()`` under the canonical name ``SVF_<job_id>_<template>_raw.<ext>``
    -> write a metadata sidecar JSON next to it.  Mutates ``job`` with the
    resulting paths and returns the imported media path.
    """
    src = Path(src_path)
    if not src.exists():
        raise FileNotFoundError(f"source media not found: {src}")
    if not is_video_file(src):
        raise ValueError(
            f"unsupported media extension {src.suffix!r}; "
            f"expected one of {sorted(VIDEO_EXTENSIONS)}"
        )

    job.raw_media_path = str(src)

    ext = src.suffix.lower()
    template = job.template or "clip"
    dest_name = f"SVF_{job.id}_{template}_raw{ext}"
    dest = config.imported_dir() / dest_name
    shutil.copy2(src, dest)
    job.imported_media_path = str(dest)

    probe = probe_video(dest)
    sidecar = {
        "job_id": job.id,
        "template": template,
        "provider": job.provider,
        "generation_mode": job.generation_mode,
        "source_path": str(src),
        "imported_path": str(dest),
        **probe,
    }
    sidecar_path = dest.with_suffix(dest.suffix + ".json")
    with sidecar_path.open("w", encoding="utf-8") as fh:
        json.dump(sidecar, fh, indent=2, ensure_ascii=False)
    job.sidecar_path = str(sidecar_path)

    return dest
