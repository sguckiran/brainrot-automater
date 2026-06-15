"""Prompt stage — build a Flow/Omni-style text-to-video generation prompt.

The prompt text is what a later browser phase pastes into Google Flow / Gemini
Omni.  In Phase 1 it is saved to a file and (for mock mode) otherwise ignored.

WHY deterministic templating: see :mod:`social_video_factory.ideas`.

TODO(hermes-llm): a later phase may replace this with a Hermes LLM call to craft
provider-tuned prompts.  Keep the signature stable.
"""

from __future__ import annotations


def build_prompt(template: str, topic: str, idea: str, script: str) -> str:
    """Return a vertical-video generation prompt string.

    Pure function combining template/topic/idea into explicit shot direction
    plus the 9:16 framing and pacing cues a generator needs.
    """
    # ``idea`` already opens with the full concept (which carries its own style,
    # pacing, treatment and camera), so we use it once here and only add 9:16
    # framing. We deliberately do NOT impose a fixed style or "fast cuts" — that
    # would override a slow, dialogue-driven concept (e.g. talking fruit) with
    # action-video pacing. ``topic`` is folded in via ``idea`` to avoid repeating
    # the (now full-sentence) concept twice.
    idea_text = idea.strip() or topic.strip() or "an unexpected moment"
    return (
        f"Vertical 9:16 short-form video. {idea_text} "
        "Centered subject framed for a 1080x1920 portrait canvas, "
        "strong first-second visual hook, looping-friendly ending. "
        "No on-screen text (captions are added in post)."
    )
