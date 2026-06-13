"""Artifact redaction + stage writing, with a fake controller."""

from __future__ import annotations

import json

import pytest

from social_video_factory import config
from social_video_factory.browser.artifacts import ArtifactLogger, redact


@pytest.fixture(autouse=True)
def _tmp_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SOCIAL_FACTORY_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


class FakeController:
    """Captures screenshot paths; returns canned HTML."""

    def __init__(self, html=""):
        self._html = html
        self.shots = []

    def screenshot(self, path):
        from pathlib import Path

        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x89PNG\r\n")  # fake image bytes
        self.shots.append(p)
        return p

    def html(self):
        return self._html


# --- redact --------------------------------------------------------------


def test_redact_removes_cookie_value():
    out = redact("Cookie: SID=abc123secretvalue; HSID=xyz")
    assert "abc123secretvalue" not in out
    assert "[REDACTED]" in out


def test_redact_removes_bearer_token():
    out = redact("Authorization: Bearer ya29.A0ARrdaMxVeryLongOpaqueToken123")
    assert "ya29.A0ARrdaMxVeryLongOpaqueToken123" not in out
    assert "[REDACTED]" in out


def test_redact_removes_api_key_and_password():
    out = redact('api_key="sk-livesecret999" password=hunter2very')
    assert "sk-livesecret999" not in out
    assert "hunter2very" not in out


def test_redact_removes_token_json():
    out = redact('{"access_token": "tok_longopaque_aaaaaaaaaaaa"}')
    assert "tok_longopaque_aaaaaaaaaaaa" not in out


def test_redact_keeps_innocuous_text():
    out = redact("Your video is ready to download.")
    assert out == "Your video is ready to download."


# --- stage ---------------------------------------------------------------


def test_stage_writes_jsonl_event_and_screenshot():
    controller = FakeController()
    logger = ArtifactLogger("job123", controller)
    logger.stage("opened", selector_used="prompt_box", note="navigated")

    log_dir = config.logs_dir() / "job123"
    assert (log_dir / "opened.png").exists()
    assert controller.shots

    events = (log_dir / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(events) == 1
    event = json.loads(events[0])
    assert event["stage"] == "opened"
    assert event["selector_used"] == "prompt_box"
    assert event["note"] == "navigated"
    assert event["ts"]


def test_stage_html_snapshot_is_redacted_and_scripts_dropped():
    html = (
        "<html><head><script>var token='sk-livesecretXYZ123';</script></head>"
        "<body>Cookie: SID=verysecretcookievalue999</body></html>"
    )
    controller = FakeController(html=html)
    logger = ArtifactLogger("job456", controller)
    logger.stage("snap", html=True)

    snapshot = (config.logs_dir() / "job456" / "snap.html").read_text(encoding="utf-8")
    # Script block removed entirely.
    assert "<script" not in snapshot
    assert "sk-livesecretXYZ123" not in snapshot
    # Cookie value scrubbed.
    assert "verysecretcookievalue999" not in snapshot
    assert "[REDACTED]" in snapshot


def test_stage_redacts_note_and_selector():
    controller = FakeController()
    logger = ArtifactLogger("job789", controller)
    logger.stage("x", note="Authorization: Bearer leakedtoken12345abcdef")
    event = json.loads(
        (config.logs_dir() / "job789" / "events.jsonl").read_text(encoding="utf-8")
    )
    assert "leakedtoken12345abcdef" not in event["note"]
