"""Keep tests isolated from the user's real Hermes publishing configuration."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_hermes_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
