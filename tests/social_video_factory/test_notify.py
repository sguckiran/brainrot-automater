"""Notifier — best-effort, credential-gated, never crashes, never logs token."""

from __future__ import annotations

import pytest

from social_video_factory import notify


@pytest.fixture(autouse=True)
def _clear_creds(monkeypatch):
    for var in (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_HOME_CHANNEL",
        "TELEGRAM_HOME_CHANNEL_THREAD_ID",
        "SOCIAL_FACTORY_DISCORD_WEBHOOK",
    ):
        monkeypatch.delenv(var, raising=False)


def test_noop_without_creds():
    # No channel configured -> quiet no-op, returns False, raises nothing.
    assert notify.notify("hello") is False


def test_empty_text_is_noop():
    assert notify.notify("") is False
    assert notify.notify("   ") is False


def test_telegram_send_uses_token_and_chat(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "SECRET123")
    monkeypatch.setenv("TELEGRAM_HOME_CHANNEL", "98765")

    captured = {}

    class _Resp:
        def raise_for_status(self):
            return None

    def _fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _Resp()

    import httpx

    monkeypatch.setattr(httpx, "post", _fake_post)

    assert notify.notify("ping") is True
    # Token goes in the URL path; chat id + text in the body.
    assert "/botSECRET123/sendMessage" in captured["url"]
    assert captured["json"]["chat_id"] == "98765"
    assert captured["json"]["text"] == "ping"


def test_send_failure_is_swallowed_and_token_not_logged(monkeypatch, caplog):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "SUPERSECRETTOKEN")
    monkeypatch.setenv("TELEGRAM_HOME_CHANNEL", "1")

    def _boom(*a, **k):
        raise RuntimeError("network down: SUPERSECRETTOKEN leaked?")

    import httpx

    monkeypatch.setattr(httpx, "post", _boom)

    with caplog.at_level("WARNING"):
        assert notify.notify("ping") is False
    # The token must never appear in logs.
    assert "SUPERSECRETTOKEN" not in caplog.text


def test_discord_webhook(monkeypatch):
    monkeypatch.setenv("SOCIAL_FACTORY_DISCORD_WEBHOOK", "https://discord/webhook/x")
    captured = {}

    class _Resp:
        def raise_for_status(self):
            return None

    def _fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _Resp()

    import httpx

    monkeypatch.setattr(httpx, "post", _fake_post)
    assert notify.notify("ping") is True
    assert captured["url"] == "https://discord/webhook/x"
    assert captured["json"]["content"] == "ping"
