"""Self-contained push notifications for the unattended autopilot loop.

WHY this exists: when the loop runs headless on a VM and hits a ``needs_human``
stop (login expired, CAPTCHA, UI drift), the user must be told — otherwise the
job just waits forever. This module sends a short message to Telegram and/or
Discord using the SAME credentials the Hermes gateway already uses, so the user
doesn't configure a second bot.

Design rules:
- Credentials come from the environment only (``TELEGRAM_BOT_TOKEN`` +
  ``TELEGRAM_HOME_CHANNEL``; optional ``SOCIAL_FACTORY_DISCORD_WEBHOOK``). We
  read the same env vars the gateway reads (see gateway/config.py).
- If nothing is configured, every function is a quiet no-op (logged at INFO) —
  notifications are best-effort and must NEVER crash an autopilot run.
- The bot token / webhook URL are NEVER logged or echoed.
- Uses ``httpx`` (a core Hermes dependency) so there is no extra install.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

ENV_TELEGRAM_TOKEN = "TELEGRAM_BOT_TOKEN"
ENV_TELEGRAM_CHAT = "TELEGRAM_HOME_CHANNEL"
ENV_TELEGRAM_THREAD = "TELEGRAM_HOME_CHANNEL_THREAD_ID"
ENV_DISCORD_WEBHOOK = "SOCIAL_FACTORY_DISCORD_WEBHOOK"

# Telegram caps messages at 4096 chars; stay well under.
_MAX_LEN = 3500


def _truncate(text: str) -> str:
    text = text.strip()
    if len(text) <= _MAX_LEN:
        return text
    return text[: _MAX_LEN - 1] + "…"


def _send_telegram(text: str) -> bool:
    token = (os.environ.get(ENV_TELEGRAM_TOKEN) or "").strip()
    chat_id = (os.environ.get(ENV_TELEGRAM_CHAT) or "").strip()
    if not token or not chat_id:
        return False
    payload: dict[str, Any] = {"chat_id": chat_id, "text": _truncate(text)}
    thread = (os.environ.get(ENV_TELEGRAM_THREAD) or "").strip()
    if thread:
        payload["message_thread_id"] = thread
    try:
        import httpx

        resp = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:  # never let a notification failure escape
        # Log the class of failure only — NOT the token / URL.
        logger.warning("telegram notify failed: %s", type(exc).__name__)
        return False


def _send_discord(text: str) -> bool:
    webhook = (os.environ.get(ENV_DISCORD_WEBHOOK) or "").strip()
    if not webhook:
        return False
    try:
        import httpx

        resp = httpx.post(webhook, json={"content": _truncate(text)}, timeout=15)
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("discord notify failed: %s", type(exc).__name__)
        return False


def notify(text: str) -> bool:
    """Best-effort push to every configured channel. True if any send succeeded.

    A quiet no-op (returns False) when no channel is configured — callers
    should treat notifications as advisory, never as a gate.
    """
    if not text or not text.strip():
        return False
    sent_telegram = _send_telegram(text)
    sent_discord = _send_discord(text)
    if not (sent_telegram or sent_discord):
        logger.info("notify: no channel configured (or all sends failed); skipping")
    return sent_telegram or sent_discord


def notify_needs_human(job: Any, reason: str) -> bool:
    """Send a concise, actionable ``needs_human`` alert for one job."""
    job_id = getattr(job, "id", "?")
    template = getattr(job, "template", "") or "?"
    topic = getattr(job, "topic", "") or "?"
    text = (
        "🟡 social_video_factory needs you\n"
        f"job {job_id} ({template} — {topic})\n"
        f"reason: {reason}\n"
        "Action: VNC into the VM and resolve it (e.g. re-login), then it resumes."
    )
    return notify(text)
