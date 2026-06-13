"""Script stage — turn an idea into a short, punchy spoken/caption script.

The script is later split into evenly-timed subtitle lines and burned into the
render, so we deliberately produce a small number of short lines.

WHY deterministic templating: see :mod:`social_video_factory.ideas`.

TODO(hermes-llm): a later phase may replace this with a Hermes LLM call for
genuinely creative scripts.  Keep the signature + "short lines" contract stable
so the SRT builder downstream is unaffected.
"""

from __future__ import annotations


def build_script(template: str, topic: str, idea: str) -> str:
    """Return a short multi-line script (newline-separated beats).

    Pure function.  Each line is intended to become one subtitle cue.
    """
    template_label = template.replace("_", " ").strip() or "this"
    topic_label = topic.strip() or "this"
    lines = [
        f"Wait til you see this {template_label}.",
        f"It is all about {topic_label}.",
        "You won't believe what happens next.",
        "Watch till the end!",
    ]
    return "\n".join(lines)
