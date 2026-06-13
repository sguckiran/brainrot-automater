"""Per-stage diagnostic artifacts (screenshots / HTML / JSONL) with redaction.

WHY: when the conservative worker pauses or stops it is invaluable to have a
screenshot + a redacted HTML snapshot + a timestamped event log of what it saw
and which selector it used.  But those artifacts MUST NEVER contain secrets:
cookies, tokens, Authorization / Bearer values, API keys, or passwords.  Every
piece of text written or printed goes through :func:`redact` first, and HTML
snapshots additionally strip ``<script>`` blocks (which often carry inlined
tokens).  We NEVER write raw cookies / tokens / auth headers.

Artifacts land under ``config.logs_dir() / <job_id> /``.  The logger is
best-effort: a failed screenshot or write must never break the generation flow.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Substrings whose surrounding value we scrub.  Matches ``key: value``,
# ``key=value``, ``"key": "value"`` etc., replacing only the value.
_SECRET_KEYS = (
    "cookie",
    "set-cookie",
    "authorization",
    "auth",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "password",
    "passwd",
    "secret",
    "api[_-]?key",
    "apikey",
    "client[_-]?secret",
    "session",
    "csrf",
    "x-goog-api-key",
)

_REDACTED = "[REDACTED]"

# key (any of the secret names) then a separator (:, =, ":") then the value
# (quoted or up to a delimiter).  Case-insensitive.
_KV_PATTERN = re.compile(
    r"(?P<key>(?:" + "|".join(_SECRET_KEYS) + r"))"
    r"(?P<sep>\s*[:=]\s*|\"\s*:\s*\"?|'\s*:\s*'?)"
    r"(?P<val>\"[^\"]*\"|'[^']*'|[^\s,;&}\"']+)",
    re.IGNORECASE,
)

# Bearer / token-style headers: ``Bearer <opaque>``.
_BEARER_PATTERN = re.compile(r"\bBearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE)

# A long opaque value (e.g. a JWT-ish or base64-ish blob) standing alone.
_OPAQUE_PATTERN = re.compile(r"\b[A-Za-z0-9_\-]{40,}\.[A-Za-z0-9_\-.]{10,}\b")

# Whole <script>...</script> blocks (frequently carry inlined session data).
_SCRIPT_PATTERN = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)


def redact(text: str) -> str:
    """Strip obvious secrets from ``text`` before it is written or printed.

    Scrubs cookie / token / authorization / password / api-key style key=value
    pairs, ``Bearer <token>`` headers, and long opaque JWT-ish blobs.  Returns a
    safe-to-store string.  This is intentionally aggressive: over-redaction is
    fine for a diagnostic artifact; leaking a secret is not.
    """
    if not text:
        return text

    def _kv_repl(match: re.Match) -> str:
        return f"{match.group('key')}{match.group('sep')}{_REDACTED}"

    # Bearer first: collapses "Bearer <token>" so a following key=value scrub
    # never leaves the opaque token dangling after the header name.
    redacted = _BEARER_PATTERN.sub(f"Bearer {_REDACTED}", text)
    redacted = _KV_PATTERN.sub(_kv_repl, redacted)
    redacted = _OPAQUE_PATTERN.sub(_REDACTED, redacted)
    return redacted


def _redact_html(html: str) -> str:
    """Redact an HTML snapshot: drop ``<script>`` blocks, then scrub secrets."""
    without_scripts = _SCRIPT_PATTERN.sub("<!-- script removed -->", html)
    return redact(without_scripts)


class ArtifactLogger:
    """Write per-stage screenshots / HTML / JSONL events for one job.

    All output goes under ``config.logs_dir() / job_id /``.  Every method is
    best-effort and swallows its own errors so diagnostics never break the flow.
    """

    def __init__(self, job_id: str, controller: Any) -> None:
        self.job_id = job_id
        self.controller = controller
        # Resolve lazily so SOCIAL_FACTORY_DATA_DIR swaps in tests are honoured.

    def _dir(self) -> Path:
        from social_video_factory import config

        path = config.logs_dir() / self.job_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def stage(
        self,
        name: str,
        *,
        selector_used: str | None = None,
        note: str | None = None,
        screenshot: bool = True,
        html: bool = False,
    ) -> None:
        """Record one pipeline stage.

        Saves (best-effort) a screenshot, optionally a REDACTED HTML snapshot,
        and always appends a JSONL event ``{stage, ts, selector_used, note}`` to
        ``events.jsonl``.  ``note`` is redacted before being stored.
        """
        directory = self._dir()
        ts = datetime.now(timezone.utc).isoformat()

        if screenshot:
            try:
                self.controller.screenshot(directory / f"{name}.png")
            except Exception:
                pass

        if html:
            try:
                raw = self.controller.html()
                snapshot = _redact_html(raw or "")
                (directory / f"{name}.html").write_text(snapshot, encoding="utf-8")
            except Exception:
                pass

        event = {
            "stage": name,
            "ts": ts,
            "selector_used": redact(selector_used) if selector_used else None,
            "note": redact(note) if note else None,
        }
        try:
            with (directory / "events.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            pass
