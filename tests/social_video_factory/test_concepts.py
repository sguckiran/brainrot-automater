from __future__ import annotations

from social_video_factory import concepts


def test_generate_concept_does_not_repeat(monkeypatch, tmp_path):
    monkeypatch.setenv("SOCIAL_FACTORY_DATA_DIR", str(tmp_path / "data"))

    first = concepts.generate_concept("cats")
    second = concepts.generate_concept("cats")

    assert first != second
    assert "Visual treatment:" in first
    assert "Camera:" in first


def test_generate_concept_persists_signature(monkeypatch, tmp_path):
    monkeypatch.setenv("SOCIAL_FACTORY_DATA_DIR", str(tmp_path / "data"))

    concepts.generate_concept("space")

    history = concepts._read_history()
    assert len(history) == 1
    # Signature is "<category>:<index>:<index>:...".
    category, *indexes = history[0].split(":")
    assert category in {"action", "fruit_talk"}
    assert len(indexes) == (6 if category == "action" else 7)


def test_generate_concept_covers_both_categories(monkeypatch, tmp_path):
    monkeypatch.setenv("SOCIAL_FACTORY_DATA_DIR", str(tmp_path / "data"))

    categories = set()
    for _ in range(60):
        concept = concepts.generate_concept("variety")
        if "conversational scene" in concept.lower():
            categories.add("fruit_talk")
        else:
            categories.add("action")

    # With 60 random draws both categories should appear (prob. of miss ~2^-60).
    assert categories == {"action", "fruit_talk"}
