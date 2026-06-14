"""Topic rotation — deterministic, persisted, config-driven."""

from __future__ import annotations

import pytest

from social_video_factory import config, topics


@pytest.fixture(autouse=True)
def _tmp_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SOCIAL_FACTORY_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def test_no_topics_configured_returns_empty(monkeypatch):
    monkeypatch.setattr(config, "autopilot_topics", lambda: [])
    monkeypatch.setattr(config, "autopilot_templates", lambda: ["dancing_cat"])
    assert topics.next_topics(3) == []


def test_rotation_advances_and_persists(monkeypatch):
    monkeypatch.setattr(config, "autopilot_topics", lambda: ["a", "b", "c"])
    monkeypatch.setattr(config, "autopilot_templates", lambda: ["t1", "t2"])
    monkeypatch.setattr(topics, "generate_concept", lambda theme: theme)

    first = topics.next_topics(2)
    assert first == [("t1", "a"), ("t2", "b")]
    # A second call continues where the cursor left off (persisted to disk).
    second = topics.next_topics(2)
    assert second == [("t1", "c"), ("t2", "a")]


def test_zero_or_negative_returns_empty(monkeypatch):
    monkeypatch.setattr(config, "autopilot_topics", lambda: ["a"])
    monkeypatch.setattr(config, "autopilot_templates", lambda: ["t1"])
    assert topics.next_topics(0) == []
    assert topics.next_topics(-1) == []


def test_cursor_not_advanced_when_nothing_produced(monkeypatch):
    # No topics -> no pairs -> cursor file should not move things forward.
    monkeypatch.setattr(config, "autopilot_topics", lambda: [])
    monkeypatch.setattr(config, "autopilot_templates", lambda: ["t1"])
    topics.next_topics(5)
    # Now configure topics; rotation should start at the beginning.
    monkeypatch.setattr(config, "autopilot_topics", lambda: ["a", "b"])
    monkeypatch.setattr(topics, "generate_concept", lambda theme: theme)
    assert topics.next_topics(1) == [("t1", "a")]


def test_rotation_expands_theme_into_fresh_concept(monkeypatch):
    monkeypatch.setattr(config, "autopilot_topics", lambda: ["space cats"])
    monkeypatch.setattr(config, "autopilot_templates", lambda: ["t1"])
    monkeypatch.setattr(
        topics,
        "generate_concept",
        lambda theme: f"fresh concept inspired by {theme}",
    )

    assert topics.next_topics(1) == [
        ("t1", "fresh concept inspired by space cats")
    ]
