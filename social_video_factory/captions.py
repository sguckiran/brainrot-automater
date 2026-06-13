"""Caption stage — produce per-platform caption text for a job.

WHY templated: Phase 1 runs without an LLM, so captions are derived
deterministically from the job's topic/idea. The shape (a dict keyed by
platform) is stable so a later phase can swap in an LLM-backed generator
without changing the pipeline or store schema.

TODO(hermes-llm): replace the templated bodies with a Hermes LLM call that
tailors tone/hashtags per platform. Keep the ``{"tiktok": ..., "instagram":
...}`` return shape.
"""

from __future__ import annotations

from social_video_factory.models import Job


def _hashtagify(topic: str) -> str:
    """Turn a topic into a couple of simple hashtags."""
    words = [w for w in topic.replace("-", " ").split() if w.isalnum()]
    tags = ["#fyp", "#shorts"]
    tags += [f"#{w.lower()}" for w in words[:3]]
    return " ".join(tags)


def build_captions(job: Job) -> dict[str, str]:
    """Return platform caption text for ``job`` as ``{"tiktok", "instagram"}``.

    Deterministic given the job's topic. Mutates nothing; the pipeline stores
    the result on the job.
    """
    topic = job.topic.strip() or "this"
    tags = _hashtagify(job.topic)
    tiktok = f"{topic} 👀 you won't believe the ending {tags}".strip()
    instagram = (
        f"{topic} — watch till the end!\n\n"
        f"Made with social_video_factory.\n{tags}"
    ).strip()
    return {"tiktok": tiktok, "instagram": instagram}
