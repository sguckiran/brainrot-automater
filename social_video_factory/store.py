"""Job persistence: one JSON file per job under :func:`config.jobs_dir`.

WHY atomic writes: a job is updated after every pipeline stage.  A crash or
concurrent reader mid-write must never observe a truncated/half-written JSON
file, so we always write to a temp file in the same directory and ``os.replace``
it over the target (an atomic rename on the same filesystem on both POSIX and
Windows).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from social_video_factory import config
from social_video_factory.models import Job


class JobStore:
    """File-backed store for :class:`Job` records.

    The store is stateless beyond its root directory, so constructing a new
    instance is cheap and every method re-resolves :func:`config.jobs_dir` —
    this keeps it honest under tests that swap ``SOCIAL_FACTORY_DATA_DIR``.
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = root

    def _dir(self) -> Path:
        return self._root if self._root is not None else config.jobs_dir()

    def _path(self, job_id: str) -> Path:
        return self._dir() / f"{job_id}.json"

    def save(self, job: Job) -> Path:
        """Atomically persist ``job`` and return its file path."""
        target = self._path(job.id)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(job.to_dict(), indent=2, ensure_ascii=False)
        # NamedTemporaryFile in the same dir guarantees os.replace is atomic.
        fd, tmp_name = tempfile.mkstemp(
            dir=str(target.parent), prefix=f".{job.id}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp_name, target)
        except BaseException:
            # Best-effort cleanup of the temp file on any failure.
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return target

    def load(self, job_id: str) -> Job:
        """Load a job by id, raising ``FileNotFoundError`` if absent."""
        path = self._path(job_id)
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return Job.from_dict(data)

    def exists(self, job_id: str) -> bool:
        return self._path(job_id).exists()

    def list_jobs(
        self,
        status: str | None = None,
        generation_mode: str | None = None,
    ) -> list[Job]:
        """Return all jobs, optionally filtered, newest-created first."""
        jobs: list[Job] = []
        for path in self._dir().glob("*.json"):
            try:
                with path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (json.JSONDecodeError, OSError):
                # Skip unreadable/half-written files rather than crash a listing.
                continue
            job = Job.from_dict(data)
            if status is not None and job.status != status:
                continue
            if generation_mode is not None and job.generation_mode != generation_mode:
                continue
            jobs.append(job)
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs
