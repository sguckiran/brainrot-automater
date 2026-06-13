"""Review stage — decide whether a job's media is acceptable.

WHY a mock backend in Phase 1: a real review would run a vision-language model
over the rendered/imported clip, which needs a backend not wired in this phase.
The mock backend is deterministic (always accepts) so the mock pipeline reaches
``awaiting_approval`` predictably. The return shape matches what a real VLM
backend would produce so the pipeline does not change when one lands.

TODO(vlm): add a VLM-backed review that inspects the actual frames and can
return ``accepted=False`` with a concrete reason. Keep the
``{"accepted", "reason", "backend"}`` shape.
"""

from __future__ import annotations

from social_video_factory.models import Job


def review(job: Job) -> dict[str, object]:
    """Return a review verdict for ``job``.

    Deterministic mock: accepts every job. The ``backend`` field marks this as
    the mock path so downstream tooling/tests can distinguish it from a future
    VLM verdict.
    """
    return {
        "accepted": True,
        "reason": "mock review backend accepts all jobs in this build",
        "backend": "mock",
    }
