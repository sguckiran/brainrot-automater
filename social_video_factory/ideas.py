"""Idea stage — turn a (template, topic) pair into a one-line creative concept.

WHY deterministic templating: Phase 1 must run fully offline with no LLM and no
network, so the creative stages are pure string functions.  This keeps the
mock E2E reproducible and testable.

TODO(hermes-llm): a later phase may swap this deterministic path for a Hermes
LLM call (e.g. an `agent/`-backed completion) to generate richer ideas.  Keep
the signature stable so the pipeline does not change when that lands.  Do NOT
import from `agent/`/`tools/` here in Phase 1.
"""

from __future__ import annotations


def build_idea(template: str, topic: str) -> str:
    """Return a single-line creative concept for ``template`` about ``topic``.

    Pure function: same inputs always yield the same idea.
    """
    topic_label = topic.strip() or "something delightfully chaotic"
    # The topic IS the concept (built by ``concepts.py``), so we present it
    # as-is and add a short hook framing rather than re-wrapping it in an
    # "about ..." clause (which reads broken for full-sentence concepts).
    return (
        f"{topic_label} "
        f"Engineered to hook viewers in the first second and keep them watching "
        f"to the very end."
    )
