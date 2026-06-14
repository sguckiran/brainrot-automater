"""Preflight checks for an unattended deployment.

WHY: the autopilot runs headless on a schedule, so a missing dependency or an
unseeded login otherwise fails silently at 3am. ``doctor`` surfaces everything
that must be true BEFORE you flip the timer on — dependencies, logged-in
profiles, notification creds, and the publishing/topic config — as a single
readable report.

Pure-ish: ``run_checks()`` returns structured results so it's unit-testable; the
CLI formats + prints them. Reports availability only — never logs secret values.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from social_video_factory import config

# Levels, ordered by severity.
OK = "ok"
WARN = "warn"
FAIL = "fail"


@dataclass
class Check:
    level: str
    name: str
    detail: str


def _profile_seeded(path) -> bool:
    try:
        return path.is_dir() and any(path.iterdir())
    except OSError:
        return False


def run_checks() -> list[Check]:
    """Return the preflight checks for the current environment + config."""
    checks: list[Check] = []

    # --- dependencies ------------------------------------------------------
    for binary in ("ffmpeg", "ffprobe"):
        if shutil.which(binary):
            checks.append(Check(OK, binary, "found on PATH"))
        else:
            checks.append(Check(FAIL, binary, "missing — render/probe will be skipped or fail"))

    try:
        import importlib.util

        if importlib.util.find_spec("playwright") is not None:
            checks.append(Check(OK, "playwright", "importable"))
        else:
            checks.append(
                Check(FAIL, "playwright", "not installed — run: uv run pip install playwright")
            )
    except Exception:
        checks.append(Check(FAIL, "playwright", "could not probe import"))

    # --- generation target -------------------------------------------------
    if config.flow_url() or config.gemini_url():
        checks.append(Check(OK, "target_url", "SOCIAL_FACTORY_FLOW_URL / GEMINI_URL set"))
    else:
        checks.append(Check(FAIL, "target_url", "set SOCIAL_FACTORY_FLOW_URL"))

    # --- logged-in profiles (seeded by a one-time manual login) ------------
    if _profile_seeded(config.profile_dir()):
        checks.append(Check(OK, "flow_profile", "Chromium profile is initialized"))
    else:
        checks.append(
            Check(FAIL, "flow_profile", "not seeded — run: browser-login --target flow")
        )
    for platform in config.publish_platforms():
        try:
            seeded = _profile_seeded(config.social_profile_dir(platform))
        except ValueError:
            continue
        if seeded:
            checks.append(Check(OK, f"{platform}_profile", "profile is initialized"))
        else:
            checks.append(
                Check(
                    WARN,
                    f"{platform}_profile",
                    f"not seeded — run: browser-login --target {platform}",
                )
            )

    # --- notifications -----------------------------------------------------
    import os

    has_telegram = bool(
        (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
        and (os.environ.get("TELEGRAM_HOME_CHANNEL") or "").strip()
    )
    has_discord = bool((os.environ.get("SOCIAL_FACTORY_DISCORD_WEBHOOK") or "").strip())
    if has_telegram or has_discord:
        chans = ", ".join(c for c, on in (("telegram", has_telegram), ("discord", has_discord)) if on)
        checks.append(Check(OK, "notifications", f"configured: {chans}"))
    else:
        checks.append(
            Check(WARN, "notifications", "no Telegram/Discord creds — you won't get needs_human alerts")
        )

    # --- supervised CAPTCHA handling --------------------------------------
    if config.supervised_pause():
        if config.novnc_url():
            checks.append(Check(OK, "supervised_pause", f"on; live view: {config.novnc_url()}"))
        else:
            checks.append(
                Check(WARN, "supervised_pause", "on but SOCIAL_FACTORY_NOVNC_URL unset — alert has no solve link")
            )
    else:
        checks.append(Check(OK, "supervised_pause", "off (challenges stop + retry next cycle)"))

    # --- publishing + autopilot config ------------------------------------
    if config.publishing_enabled():
        auto = "auto-publish ON" if config.auto_publish() else "manual publish only"
        checks.append(
            Check(OK, "publishing", f"enabled ({auto}); platforms: {', '.join(config.publish_platforms())}")
        )
    else:
        checks.append(Check(WARN, "publishing", "disabled — generation only, nothing posts"))

    if config.autopilot_topics():
        checks.append(
            Check(
                OK,
                "autopilot_topics",
                f"{len(config.autopilot_topics())} topic(s); per_run_limit={config.autopilot_per_run_limit()}",
            )
        )
    else:
        checks.append(
            Check(WARN, "autopilot_topics", "none configured — autopilot will idle ('nothing to do')")
        )

    # --- unattended sanity -------------------------------------------------
    if config.require_human_confirm_every() != 0:
        checks.append(
            Check(
                WARN,
                "human_confirm",
                f"REQUIRE_HUMAN_CONFIRM_EVERY={config.require_human_confirm_every()} — set 0 for unattended (else it blocks on stdin)",
            )
        )
    else:
        checks.append(Check(OK, "human_confirm", "disabled (0) — safe for unattended"))

    return checks


def summarize(checks: list[Check]) -> tuple[int, int, int]:
    """Return (ok, warn, fail) counts."""
    ok = sum(1 for c in checks if c.level == OK)
    warn = sum(1 for c in checks if c.level == WARN)
    fail = sum(1 for c in checks if c.level == FAIL)
    return ok, warn, fail
