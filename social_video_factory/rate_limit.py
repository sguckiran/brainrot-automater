"""Local-only generation rate limiter.

WHY this exists: the browser worker drives the user's OWN subscription.  Even
when the website would allow more, we ALWAYS respect a conservative local budget
(per-hour, per-day, a minimum gap between generations) and prompt for human
confirmation every N generations (the checkpoint falls BEFORE the (N+1)th,
(2N+1)th, … generation — never before the first).  This is a safety /
good-citizen control, not
a website limit, so it is enforced here regardless of what the UI permits.

The state lives in ``config.state_dir() / "rate_limit.json"`` as::

    {"generations": ["<iso ts>", ...], "total_count": <int>}

Writes are atomic (same temp-file + ``os.replace`` pattern as ``store.py``) so a
crash mid-write never corrupts the budget.

``now`` (clock) and ``confirm`` (human y/N) are injected for testability; the
defaults are the real wall clock and an ``input()``-based prompt.  The module is
deliberately dependency-light: stdlib + :mod:`config` only.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from social_video_factory import config

_STATE_FILENAME = "rate_limit.json"


def _real_now() -> datetime:
    """Default clock: timezone-aware UTC now (injectable for tests)."""
    return datetime.now(timezone.utc)


def _input_confirm(prompt: str) -> bool:
    """Default human confirm: ask on stdin, treat only an explicit 'y' as yes."""
    try:
        answer = input(prompt)
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip().lower() in {"y", "yes"}


@dataclass
class RateDecision:
    """Outcome of :meth:`RateLimiter.check`.

    ``allowed``      — may the worker proceed at all (caps + min-gap satisfied)?
    ``reason``       — human-readable denial reason when ``allowed`` is False.
    ``needs_human_confirm`` — a periodic human-confirmation prompt is due.
    """

    allowed: bool
    reason: str | None = None
    needs_human_confirm: bool = False


class RateLimiter:
    """Persisted per-hour / per-day / min-gap / human-confirm-every limiter."""

    def __init__(
        self,
        *,
        now: Callable[[], datetime] = _real_now,
        confirm: Callable[[str], bool] = _input_confirm,
        state_path: Path | None = None,
    ) -> None:
        self._now = now
        self.confirm = confirm
        # Resolve the path lazily by default so tests that swap the data dir win.
        self._state_path = state_path

    # -- persistence --------------------------------------------------------

    def _path(self) -> Path:
        return self._state_path or (config.state_dir() / _STATE_FILENAME)

    def _load(self) -> dict:
        """Load state, pruning generation timestamps older than 24h.

        Tolerates a missing / corrupt file by starting from an empty budget —
        the limiter should never crash the worker on a bad state file.
        """
        path = self._path()
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            data = {}

        raw_ts = data.get("generations") or []
        cutoff = self._now() - timedelta(days=1)
        kept: list[datetime] = []
        for item in raw_ts:
            parsed = _parse_iso(item)
            if parsed is not None and parsed >= cutoff:
                kept.append(parsed)
        return {
            "generations": kept,
            "total_count": int(data.get("total_count") or 0),
        }

    def _save(self, generations: list[datetime], total_count: int) -> None:
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "generations": [_to_iso(ts) for ts in generations],
                "total_count": total_count,
            },
            indent=2,
        )
        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=".rate_limit.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    # -- public API ---------------------------------------------------------

    def check(self) -> RateDecision:
        """Decide whether a generation may proceed right now.

        Denies (``allowed=False``) when the last-hour count has reached the
        hourly cap, the last-day count has reached the daily cap, or fewer than
        ``min_seconds_between_generations`` have elapsed since the last
        generation.  Caps of 0 disable that particular limit.

        Sets ``needs_human_confirm=True`` (without denying) when a periodic
        human checkpoint is due: ``require_human_confirm_every`` is positive,
        at least one generation has already been recorded
        (``total_count > 0``), and ``total_count % require_human_confirm_every
        == 0``.  The ``total_count > 0`` guard is deliberate — without it the
        checkpoint fires before the FIRST generation (``0 % N == 0``), which in
        a non-interactive context (the default ``input()`` confirm raises
        ``EOFError`` → declined) would make every automated generation decline
        and never start.  So the checkpoint falls before the (N+1)th,
        (2N+1)th, … generation, never before the 1st.
        """
        state = self._load()
        generations: list[datetime] = state["generations"]
        total_count: int = state["total_count"]
        now = self._now()

        hourly_cap = config.max_generations_per_hour()
        daily_cap = config.max_generations_per_day()
        min_gap = config.min_seconds_between_generations()
        confirm_every = config.require_human_confirm_every()

        hour_ago = now - timedelta(hours=1)
        day_ago = now - timedelta(days=1)
        last_hour = sum(1 for ts in generations if ts >= hour_ago)
        last_day = sum(1 for ts in generations if ts >= day_ago)

        if hourly_cap > 0 and last_hour >= hourly_cap:
            return RateDecision(
                allowed=False,
                reason=(
                    f"hourly cap reached ({last_hour}/{hourly_cap} in the last hour)"
                ),
            )
        if daily_cap > 0 and last_day >= daily_cap:
            return RateDecision(
                allowed=False,
                reason=f"daily cap reached ({last_day}/{daily_cap} in the last day)",
            )
        if min_gap > 0 and generations:
            last_ts = max(generations)
            elapsed = (now - last_ts).total_seconds()
            if elapsed < min_gap:
                wait = int(min_gap - elapsed)
                return RateDecision(
                    allowed=False,
                    reason=(
                        f"minimum gap not met ({int(elapsed)}s since last; "
                        f"need {min_gap}s — wait ~{wait}s)"
                    ),
                )

        needs_confirm = (
            confirm_every > 0
            and total_count > 0
            and (total_count % confirm_every == 0)
        )
        return RateDecision(allowed=True, reason=None, needs_human_confirm=needs_confirm)

    def record(self) -> None:
        """Record one successful generation: append ``now()`` + bump the count."""
        state = self._load()
        generations: list[datetime] = state["generations"]
        generations.append(self._now())
        self._save(generations, state["total_count"] + 1)


def _to_iso(ts: datetime) -> str:
    """Serialise a datetime to ISO-8601 (UTC-normalised)."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).isoformat()


def _parse_iso(value: object) -> datetime | None:
    """Parse an ISO timestamp back to an aware UTC datetime, or ``None``."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
