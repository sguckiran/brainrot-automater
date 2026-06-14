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
    assert len(history[0].split(":")) == 6
