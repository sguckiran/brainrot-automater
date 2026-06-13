"""Domain models: enums + the :class:`Job` dataclass.

WHY a plain dataclass with explicit ``to_dict``/``from_dict`` rather than
pydantic: this package must stay importable without the heavy Hermes dep tree,
and JSON round-trip is the only serialization we need.  Keeping the shape
explicit also documents — in one place — every field the *later* phases will
populate (browser import, review, render), so downstream agents can build on a
stable schema rather than discovering fields ad hoc.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class GenerationMode(str, Enum):
    """How the source clip is produced."""

    MOCK = "mock"
    FLOW_IMPORT = "flow_import"
    ASSISTED_FLOW = "assisted_flow"
    BROWSER_FLOW = "browser_flow"
    API_VEO = "api_veo"  # kept in the enum but disabled in this build


class JobStatus(str, Enum):
    """Pipeline stage / terminal state of a job."""

    CREATED = "created"
    IDEA = "idea"
    SCRIPTED = "scripted"
    PROMPTED = "prompted"
    GENERATING = "generating"
    IMPORTED = "imported"
    PROBED = "probed"
    REVIEWING = "reviewing"
    REJECTED = "rejected"
    ACCEPTED = "accepted"
    RENDERED = "rendered"
    CAPTIONED = "captioned"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    NEEDS_HUMAN = "needs_human"
    FAILED = "failed"


# Provider markers — chosen from --target flow|gemini.  Stored on the job and
# echoed into media sidecars so downstream tooling can attribute the clip.
PROVIDER_GOOGLE_FLOW_BROWSER = "google_flow_browser"
PROVIDER_GEMINI_OMNI_BROWSER = "gemini_omni_browser"


def _now() -> str:
    """ISO-8601 UTC timestamp (second precision is enough for stage history)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class Job:
    """A single short-video job, persisted as JSON by :mod:`store`.

    Every field a later phase needs is declared here so the on-disk schema is
    stable.  Phase-1 code only populates a subset.
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    template: str = ""
    topic: str = ""
    generation_mode: str = GenerationMode.MOCK.value
    target: str = "flow"
    status: str = JobStatus.CREATED.value
    provider: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    # creative stages
    idea: str = ""
    script: str = ""
    prompt: str = ""
    prompt_path: str | None = None

    # media paths
    raw_media_path: str | None = None
    imported_media_path: str | None = None
    sidecar_path: str | None = None
    rendered_path: str | None = None

    # downstream artifacts
    captions: dict[str, Any] = field(default_factory=dict)
    review: dict[str, Any] = field(default_factory=dict)

    # human-in-the-loop / errors
    needs_human_reason: str | None = None
    error: str | None = None

    # stage history: list of {status, ts, note}
    history: list[dict[str, Any]] = field(default_factory=list)

    def advance(self, status: str | JobStatus, note: str | None = None) -> "Job":
        """Move the job to ``status``, record a history event, bump ``updated_at``.

        Returns ``self`` so callers can chain.  This is the ONLY sanctioned way
        to change ``status`` so the history stays an accurate audit trail.
        """
        status_value = status.value if isinstance(status, JobStatus) else str(status)
        self.status = status_value
        self.updated_at = _now()
        self.history.append(
            {"status": status_value, "ts": self.updated_at, "note": note}
        )
        return self

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict representation suitable for ``json.dump``."""
        return {
            "id": self.id,
            "template": self.template,
            "topic": self.topic,
            "generation_mode": self.generation_mode,
            "target": self.target,
            "status": self.status,
            "provider": self.provider,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "idea": self.idea,
            "script": self.script,
            "prompt": self.prompt,
            "prompt_path": self.prompt_path,
            "raw_media_path": self.raw_media_path,
            "imported_media_path": self.imported_media_path,
            "sidecar_path": self.sidecar_path,
            "rendered_path": self.rendered_path,
            "captions": self.captions,
            "review": self.review,
            "needs_human_reason": self.needs_human_reason,
            "error": self.error,
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Job":
        """Reconstruct a :class:`Job` from ``to_dict`` output.

        Unknown keys are ignored and missing keys fall back to field defaults,
        so the schema can grow without breaking older job files.
        """
        known = {f for f in cls.__dataclass_fields__}  # noqa: C416 - explicit set
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)
