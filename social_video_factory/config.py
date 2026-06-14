"""Environment-driven configuration + lazy path helpers.

WHY this shape:
- The whole factory keeps its runtime state under a single data root
  (``.social_video_factory/`` by default) so it is trivial to gitignore and to
  point at a throwaway directory in tests via ``SOCIAL_FACTORY_DATA_DIR``.  Every
  test sets that env var so nothing ever writes into the repo.
- All tunables are environment variables with sane defaults, loaded through
  ``python-dotenv`` so a project ``.env`` is honoured.  ALL of the plan's
  ``SOCIAL_FACTORY_*`` vars are defined here NOW (including the browser /
  rate-limit ones) even though only the Phase-1 code paths read them — later
  phases just read the helpers below instead of re-declaring env handling.
- Path helpers create their directory lazily on first access so callers never
  have to ``mkdir`` defensively.

Resolution rule: the data root is resolved relative to the *current working
directory* at call time (not import time), so a test that sets
``SOCIAL_FACTORY_DATA_DIR`` to a tmp path before invoking the pipeline gets an
isolated tree.  We intentionally re-read the env on every call for that reason.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import yaml

# Load a project .env once at import.  load_dotenv() is a no-op if absent and
# never overrides already-set process env vars, so tests that set
# SOCIAL_FACTORY_DATA_DIR via monkeypatch still win.
load_dotenv()

# --- env var names (single source of truth) -------------------------------

ENV_DATA_DIR = "SOCIAL_FACTORY_DATA_DIR"

ENV_BROWSER_PROFILE_DIR = "SOCIAL_FACTORY_BROWSER_PROFILE_DIR"
ENV_BROWSER_EXECUTABLE_PATH = "SOCIAL_FACTORY_BROWSER_EXECUTABLE_PATH"
ENV_BROWSER_HEADLESS = "SOCIAL_FACTORY_BROWSER_HEADLESS"
ENV_FLOW_URL = "SOCIAL_FACTORY_FLOW_URL"
ENV_GEMINI_URL = "SOCIAL_FACTORY_GEMINI_URL"
ENV_BROWSER_DOWNLOAD_DIR = "SOCIAL_FACTORY_BROWSER_DOWNLOAD_DIR"
ENV_MAX_GEN_PER_HOUR = "SOCIAL_FACTORY_BROWSER_MAX_GENERATIONS_PER_HOUR"
ENV_MAX_GEN_PER_DAY = "SOCIAL_FACTORY_BROWSER_MAX_GENERATIONS_PER_DAY"
ENV_MIN_SECONDS_BETWEEN_GEN = "SOCIAL_FACTORY_BROWSER_MIN_SECONDS_BETWEEN_GENERATIONS"
ENV_REQUIRE_HUMAN_CONFIRM_EVERY = "SOCIAL_FACTORY_BROWSER_REQUIRE_HUMAN_CONFIRM_EVERY"
ENV_SELECTORS_FILE = "SOCIAL_FACTORY_SELECTORS_FILE"
ENV_AUTO_PUBLISH = "SOCIAL_FACTORY_AUTO_PUBLISH"
ENV_SUPERVISED_PAUSE = "SOCIAL_FACTORY_SUPERVISED_PAUSE"
ENV_SUPERVISED_PAUSE_TIMEOUT = "SOCIAL_FACTORY_SUPERVISED_PAUSE_TIMEOUT"
ENV_NOVNC_URL = "SOCIAL_FACTORY_NOVNC_URL"

# Default data root, relative to CWD unless SOCIAL_FACTORY_DATA_DIR is set.
DEFAULT_DATA_DIR_NAME = ".social_video_factory"

# Watermark / branding text burned into rendered videos (Phase 1 default).
WATERMARK_TEXT = os.environ.get("SOCIAL_FACTORY_WATERMARK", "@social_video_factory")


def _bool_env(name: str, default: bool) -> bool:
    """Parse a boolean env var with the usual truthy spellings."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# --- data root + path helpers ---------------------------------------------


def data_dir() -> Path:
    """Return the runtime data root, creating it lazily.

    Resolved from ``SOCIAL_FACTORY_DATA_DIR`` if set, otherwise
    ``<cwd>/.social_video_factory``.
    """
    override = os.environ.get(ENV_DATA_DIR)
    root = Path(override) if override else (Path.cwd() / DEFAULT_DATA_DIR_NAME)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _sub(*parts: str) -> Path:
    path = data_dir().joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def jobs_dir() -> Path:
    """Directory holding per-job JSON state (``<job_id>.json``)."""
    return _sub("jobs")


def profile_dir() -> Path:
    """Persistent Chromium profile dir (used by later browser phases)."""
    override = os.environ.get(ENV_BROWSER_PROFILE_DIR)
    if override:
        path = Path(override)
        path.mkdir(parents=True, exist_ok=True)
        return path
    return _sub("chromium_profile")


def social_profile_dir(platform: str) -> Path:
    """Persistent browser profile for a social publishing platform."""
    normalized = platform.strip().lower()
    if normalized not in {"instagram", "tiktok"}:
        raise ValueError(f"unsupported social platform: {platform!r}")
    return _sub("social_profiles", normalized)


def downloads_dir() -> Path:
    """Where the browser worker drops downloaded clips (later phases)."""
    override = os.environ.get(ENV_BROWSER_DOWNLOAD_DIR)
    if override:
        path = Path(override)
        path.mkdir(parents=True, exist_ok=True)
        return path
    return _sub("media", "browser_downloads")


def imported_dir() -> Path:
    """Where verified/renamed source clips land."""
    return _sub("media", "imported")


def rendered_dir() -> Path:
    """Where finished 9:16 renders land."""
    return _sub("media", "rendered")


def state_dir() -> Path:
    """Rate-limit + counter state (later phases)."""
    return _sub("state")


def logs_dir() -> Path:
    """Screenshots / HTML / stage logs (later phases)."""
    return _sub("logs")


# --- browser / rate-limit config accessors (defined now, used later) -------


def browser_executable_path() -> str | None:
    """Explicit Chromium path, or ``None`` to use Playwright's bundled build."""
    value = os.environ.get(ENV_BROWSER_EXECUTABLE_PATH, "").strip()
    return value or None


def browser_headless() -> bool:
    """Headed by default (the real generation engine wants a visible browser)."""
    return _bool_env(ENV_BROWSER_HEADLESS, default=False)


def flow_url() -> str:
    return os.environ.get(ENV_FLOW_URL, "").strip()


def gemini_url() -> str:
    return os.environ.get(ENV_GEMINI_URL, "").strip()


def max_generations_per_hour() -> int:
    return _int_env(ENV_MAX_GEN_PER_HOUR, 3)


def max_generations_per_day() -> int:
    return _int_env(ENV_MAX_GEN_PER_DAY, 20)


def min_seconds_between_generations() -> int:
    return _int_env(ENV_MIN_SECONDS_BETWEEN_GEN, 180)


def require_human_confirm_every() -> int:
    return _int_env(ENV_REQUIRE_HUMAN_CONFIRM_EVERY, 10)


def selectors_file() -> str:
    """Path to the user's selector overrides, or '' to use the bundled example."""
    return os.environ.get(ENV_SELECTORS_FILE, "").strip()


def supervised_pause() -> bool:
    """Whether to HOLD the browser open on a human-solvable challenge.

    When true, a CAPTCHA / verification / consent screen does NOT immediately
    end the run: the worker notifies (with the noVNC link) and waits for the
    user to clear the challenge in the live session, then continues. The user
    still solves it — we never solve or bypass it. Default false (pure
    unattended exits fast and retries next cycle).
    """
    return _bool_env(ENV_SUPERVISED_PAUSE, default=False)


def supervised_pause_timeout() -> int:
    """How long (seconds) to hold the browser waiting for the human (default 600)."""
    return _int_env(ENV_SUPERVISED_PAUSE_TIMEOUT, 600)


def novnc_url() -> str:
    """URL of the VM's noVNC view of the live browser, included in alerts ('' if unset)."""
    return os.environ.get(ENV_NOVNC_URL, "").strip()


def _hermes_config() -> dict[str, Any]:
    """Read user-facing publishing settings from Hermes config.yaml."""
    try:
        from hermes_constants import get_hermes_home

        hermes_home = get_hermes_home()
    except ImportError:
        hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    path = hermes_home / "config.yaml"
    try:
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _publish_config() -> dict[str, Any]:
    root = _hermes_config().get("social_video_factory", {})
    if not isinstance(root, dict):
        return {}
    value = root.get("publishing", {})
    return value if isinstance(value, dict) else {}


def publishing_enabled() -> bool:
    """Whether browser publishing is explicitly enabled by the user."""
    return bool(_publish_config().get("enabled", False))


def auto_publish() -> bool:
    """Whether successful generation should continue into publishing."""
    configured = _publish_config().get("auto_after_generation")
    if configured is not None:
        return publishing_enabled() and bool(configured)
    # Legacy compatibility for the original unused environment switch.
    return publishing_enabled() and _bool_env(ENV_AUTO_PUBLISH, default=False)


def publish_platforms() -> list[str]:
    """Configured publishing targets, normalized and de-duplicated."""
    raw = _publish_config().get("platforms", ["instagram", "tiktok"])
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return ["instagram", "tiktok"]
    result: list[str] = []
    for value in raw:
        platform = str(value).strip().lower()
        if platform in {"instagram", "tiktok"} and platform not in result:
            result.append(platform)
    return result or ["instagram", "tiktok"]


def burn_text_overlays() -> bool:
    """Whether render should burn scripts/hooks/watermarks into the video."""
    root = _hermes_config().get("social_video_factory", {})
    if not isinstance(root, dict):
        return False
    rendering = root.get("rendering", {})
    if not isinstance(rendering, dict):
        return False
    return bool(rendering.get("burn_text_overlays", False))


# --- autopilot (unattended loop) config ------------------------------------


def _autopilot_config() -> dict[str, Any]:
    root = _hermes_config().get("social_video_factory", {})
    if not isinstance(root, dict):
        return {}
    value = root.get("autopilot", {})
    return value if isinstance(value, dict) else {}


def _str_list(value: Any) -> list[str]:
    """Coerce a config value into a clean list of non-empty strings."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def autopilot_templates() -> list[str]:
    """Template names the unattended loop rotates through (default: one)."""
    return _str_list(_autopilot_config().get("templates")) or ["dancing_cat"]


def autopilot_topics() -> list[str]:
    """Topic strings the unattended loop rotates through.

    Empty by default — the loop only enqueues new work when topics are
    configured, so a fresh install never posts until the user opts in.
    """
    return _str_list(_autopilot_config().get("topics"))


def autopilot_target_pending() -> int:
    """How many pending browser_flow jobs to keep queued (default 3)."""
    value = _autopilot_config().get("target_pending", 3)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 3


def autopilot_per_run_limit() -> int:
    """How many jobs a single autopilot pass will generate (default 2)."""
    value = _autopilot_config().get("per_run_limit", 2)
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 2
