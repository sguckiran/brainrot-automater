#!/usr/bin/env python3
"""Social Video Factory — Hermes tool surface (Phase 5).

Exposes the ``social_video_factory`` package to the Hermes agent as four
self-registering tools (toolset ``social_video_factory``):

  * ``social_video_factory_browser_login`` — returns SAFE guidance for the
    one-time, human-driven login (never drives login itself).
  * ``social_video_factory_browser_generate_job`` — runs ONE browser
    generation for a prepared job and continues the pipeline.
  * ``social_video_factory_browser_run_queue`` — runs several prepared
    ``browser_flow`` jobs one-by-one.
  * ``social_video_factory_import_latest_browser_download`` — manual-recovery
    import of the newest browser download.

SAFETY POSTURE (every tool, enforced here):
  * The browser path drives the user's OWN logged-in Chromium profile against
    their existing subscription.  It NEVER bypasses login, usage limits, or
    safety, and NEVER auto-publishes.
  * CRITICAL — NON-INTERACTIVE: the underlying worker/queue can hit two stdin
    gates — the rate-limit human-confirm (``RateLimiter.confirm``) and the
    selector ``manual_pause`` (``controller.wait_for_enter``).  A Hermes tool
    must NEVER block on stdin.  We achieve this WITHOUT modifying
    ``worker.py`` / ``selectors.py`` / ``rate_limit.py`` by:
      - injecting ``RateLimiter(confirm=lambda _msg: False)`` so a due
        human-confirm cleanly returns a ``needs_human`` outcome instead of
        blocking; and
      - wrapping the real controller in :class:`_NonBlockingController`, whose
        ``wait_for_enter`` is a non-blocking no-op (it may log, but NEVER reads
        stdin) while every other method delegates to the real controller.
    Net effect: a ``manual_pause`` records its note and returns immediately;
    the worker's existing downstream checks (no video found, etc.) then resolve
    to a ``needs_human`` outcome with artifacts — no hang.

All ``social_video_factory.*`` imports are LAZY (inside handlers / the check
fn) to keep ``tools`` discovery cheap and avoid import cycles.  Playwright is
NOT required for tool availability — the login (guidance) and import tools work
without it.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from tools.registry import registry, tool_error

logger = logging.getLogger(__name__)

_TOOLSET = "social_video_factory"


# ---------------------------------------------------------------------------
# Availability check
# ---------------------------------------------------------------------------


def _svf_available() -> bool:
    """True when the ``social_video_factory`` package imports.

    Deliberately does NOT require Playwright: the login (guidance) and import
    tools are useful without a browser dependency installed.  In-repo this is
    always importable.
    """
    try:
        import social_video_factory  # noqa: F401  (import-only probe)

        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("social_video_factory unavailable: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Non-blocking controller adapter (the core safety primitive)
# ---------------------------------------------------------------------------


class _NonBlockingController:
    """Wrap a real :class:`BrowserController` so ``wait_for_enter`` never blocks.

    Every attribute access delegates to the wrapped controller via
    ``__getattr__`` (including ``page``, ``start``, ``goto``, ``html``,
    ``expect_download``, ``screenshot``, ``close``, ...).  Only
    ``wait_for_enter`` is overridden: it logs the message and returns
    immediately, NEVER reading stdin.  This is what keeps a Hermes tool from
    hanging if the worker hits a ``manual_pause``.
    """

    def __init__(self, inner: Any) -> None:
        # Bypass __setattr__/__getattr__ recursion by writing to __dict__.
        object.__setattr__(self, "_inner", inner)

    def wait_for_enter(self, message: str) -> None:
        """Non-blocking no-op stand-in for the interactive Enter gate."""
        logger.info(
            "social_video_factory: manual pause skipped (non-interactive tool): %s",
            message,
        )
        return None

    def __getattr__(self, name: str) -> Any:
        # Only reached for attributes not found on this instance/class, so it
        # never shadows wait_for_enter.  Delegates everything else.
        return getattr(object.__getattribute__(self, "_inner"), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(object.__getattribute__(self, "_inner"), name, value)


def _non_interactive_rate_limiter() -> Any:
    """Build a RateLimiter whose human-confirm gate auto-declines (no stdin)."""
    from social_video_factory.rate_limit import RateLimiter

    return RateLimiter(confirm=lambda _msg: False)


def _wrapped_controller() -> Any:
    """Return a non-blocking-wrapped real controller (may be a NullController)."""
    from social_video_factory.browser.controller import get_controller

    return _NonBlockingController(get_controller())


# ---------------------------------------------------------------------------
# Tool 1: browser_login (guidance only — NEVER drives login)
# ---------------------------------------------------------------------------

_LOGIN_SCHEMA: Dict[str, Any] = {
    "name": "social_video_factory_browser_login",
    "description": (
        "Return SAFE guidance for the one-time, human-driven browser login "
        "used by social_video_factory's browser_flow mode. Login REQUIRES a "
        "human at a terminal (you sign in to your OWN Flow/Gemini account in a "
        "real Chromium window), so this tool does NOT and CANNOT perform or "
        "bypass login — it only returns the exact CLI command to run, the "
        "resolved target URL (or a note that SOCIAL_FACTORY_FLOW_URL / "
        "SOCIAL_FACTORY_GEMINI_URL must be set), and whether the persistent "
        "profile directory already exists and looks initialized. Drives your "
        "OWN logged-in profile; never bypasses login/limits/safety; no "
        "auto-publish; never opens a browser."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "enum": ["flow", "gemini"],
                "description": "Which web UI to log in to (default flow).",
                "default": "flow",
            },
            "url": {
                "type": "string",
                "description": (
                    "Optional explicit URL to report instead of the configured "
                    "SOCIAL_FACTORY_FLOW_URL / SOCIAL_FACTORY_GEMINI_URL."
                ),
            },
        },
        "required": [],
    },
}


def _profile_initialized() -> bool:
    """True when the persistent profile dir exists AND is non-empty."""
    from social_video_factory import config

    try:
        profile = config.profile_dir()
        return profile.is_dir() and any(profile.iterdir())
    except Exception:
        return False


def _handle_browser_login(args: Dict[str, Any], **_kw: Any) -> str:
    from social_video_factory import config

    target = (args.get("target") or "flow").strip().lower()
    if target not in {"flow", "gemini"}:
        return tool_error(
            f"invalid target {target!r}; expected 'flow' or 'gemini'"
        )

    explicit_url = (args.get("url") or "").strip() or None
    configured_url = config.gemini_url() if target == "gemini" else config.flow_url()
    resolved_url = explicit_url or configured_url or None
    env_var = (
        "SOCIAL_FACTORY_GEMINI_URL" if target == "gemini" else "SOCIAL_FACTORY_FLOW_URL"
    )

    command = f"python -m social_video_factory.cli browser-login --target {target}"

    payload: Dict[str, Any] = {
        "status": "guidance",
        "target": target,
        "command": command,
        "resolved_url": resolved_url,
        "url_note": (
            None
            if resolved_url
            else f"no URL configured; set {env_var} (or pass url) before logging in"
        ),
        "profile_dir": str(config.profile_dir()),
        "profile_exists": _profile_initialized(),
        "note": (
            "Login is manual and human-driven: run the command above in your "
            "terminal, sign in to your OWN account in the Chromium window that "
            "opens, then press Enter there to persist the profile. This tool "
            "never performs, automates, or bypasses login."
        ),
    }
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 2: browser_generate_job
# ---------------------------------------------------------------------------

_GENERATE_SCHEMA: Dict[str, Any] = {
    "name": "social_video_factory_browser_generate_job",
    "description": (
        "Create and run ONE conservative browser video generation, or resume "
        "an existing social_video_factory job_id, then continue the pipeline "
        "to awaiting_approval. For a new job pass topic plus optional template "
        "and target. Drives "
        "the user's OWN logged-in Chromium profile; runs NON-INTERACTIVELY (it "
        "never blocks on stdin — a due human-confirm or manual pause resolves "
        "to a needs_human outcome instead of hanging). NEVER bypasses login, "
        "usage limits, or safety refusals; NEVER auto-publishes. Returns "
        "JSON {status, job_id, downloaded_path, reason, job_status}; status is "
        "one of success | needs_human | rate_limited | error."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "job_id": {
                "type": "string",
                "description": (
                    "Optional id of an existing prepared job. Omit it to create "
                    "a new job from topic."
                ),
            },
            "topic": {
                "type": "string",
                "description": "Topic for a new video job when job_id is omitted.",
            },
            "template": {
                "type": "string",
                "description": "Creative template for a new job.",
                "default": "dancing_cat",
            },
            "target": {
                "type": "string",
                "enum": ["flow", "gemini"],
                "description": "Browser generation target for a new job.",
                "default": "flow",
            },
        },
        "required": [],
    },
}


def _ensure_prompt(job: Any, store: Any) -> None:
    """Build + save the prompt if the job doesn't have one yet."""
    from social_video_factory import pipeline

    if job.prompt:
        return
    pipeline.run_idea(job, store)
    pipeline.run_script(job, store)
    pipeline.run_prompt(job, store)
    pipeline.save_prompt_file(job, store)


def _handle_browser_generate_job(args: Dict[str, Any], **_kw: Any) -> str:
    job_id = (args.get("job_id") or "").strip()

    from social_video_factory import pipeline
    from social_video_factory.browser.controller import BrowserUnavailable
    from social_video_factory.browser.worker import generate_in_browser
    from social_video_factory.models import GenerationMode
    from social_video_factory.store import JobStore

    store = JobStore()
    if job_id:
        try:
            job = store.load(job_id)
        except FileNotFoundError:
            return tool_error(f"job not found: {job_id}", job_id=job_id)
    else:
        topic = (args.get("topic") or "").strip()
        if not topic:
            return tool_error("provide job_id or topic")
        target = (args.get("target") or "flow").strip().lower()
        if target not in {"flow", "gemini"}:
            return tool_error(
                f"invalid target {target!r}; expected 'flow' or 'gemini'"
            )
        template = (args.get("template") or "dancing_cat").strip()
        job = pipeline.create_job(
            template=template,
            topic=topic,
            generation_mode=GenerationMode.BROWSER_FLOW.value,
            target=target,
            store=store,
        )
        job_id = job.id

    _ensure_prompt(job, store)

    try:
        outcome = generate_in_browser(
            job,
            store,
            controller=_wrapped_controller(),
            rate_limiter=_non_interactive_rate_limiter(),
        )
    except BrowserUnavailable as exc:
        return tool_error(str(exc), job_id=job_id, error_type="browser_unavailable")

    reloaded = store.load(job.id)
    return json.dumps(
        {
            "status": outcome.status,
            "job_id": outcome.job_id,
            "downloaded_path": outcome.downloaded_path,
            "reason": outcome.reason,
            "job_status": reloaded.status,
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# Tool 3: browser_run_queue
# ---------------------------------------------------------------------------

_RUN_QUEUE_SCHEMA: Dict[str, Any] = {
    "name": "social_video_factory_browser_run_queue",
    "description": (
        "Process up to `limit` prepared browser_flow jobs one-by-one through "
        "the conservative browser worker, pausing between successes and "
        "STOPPING on the first needs_human / error / rate_limited outcome. "
        "Drives the user's OWN logged-in Chromium profile; runs NON-"
        "INTERACTIVELY (never blocks on stdin). NEVER bypasses login, usage "
        "limits, or safety; NEVER auto-publishes. Returns JSON {processed, "
        "stopped_reason, outcomes:[{status, job_id, downloaded_path, reason}]}."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Maximum number of jobs to process (default 5).",
                "default": 5,
            },
        },
        "required": [],
    },
}


def _coerce_limit(value: Any, default: int = 5) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _handle_browser_run_queue(args: Dict[str, Any], **_kw: Any) -> str:
    limit = _coerce_limit(args.get("limit"), default=5)

    from social_video_factory.browser import queue as queue_mod
    from social_video_factory.browser.worker import generate_in_browser

    def _generate(job: Any, store: Any) -> Any:
        # Each per-job worker call is non-interactive too.
        return generate_in_browser(
            job,
            store,
            controller=_wrapped_controller(),
            rate_limiter=_non_interactive_rate_limiter(),
        )

    result = queue_mod.run_queue(limit, generate=_generate)

    return json.dumps(
        {
            "processed": result.processed,
            "stopped_reason": result.stopped_reason,
            "outcomes": [
                {
                    "status": o.status,
                    "job_id": o.job_id,
                    "downloaded_path": o.downloaded_path,
                    "reason": o.reason,
                }
                for o in result.outcomes
            ],
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# Tool 4: import_latest_browser_download
# ---------------------------------------------------------------------------

_IMPORT_SCHEMA: Dict[str, Any] = {
    "name": "social_video_factory_import_latest_browser_download",
    "description": (
        "Manual-recovery path: find the NEWEST video in the browser downloads "
        "dir, import it for the given job, then continue the pipeline (review "
        "-> render -> captions -> awaiting_approval). Use after a manual browser "
        "step left a finished clip in the downloads folder. NEVER auto-"
        "publishes. Returns the job summary JSON {id, status, "
        "imported_media_path, rendered_path, captions, ...}."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "job_id": {
                "type": "string",
                "description": "Id of the job to import the download for.",
            },
        },
        "required": ["job_id"],
    },
}


def _handle_import_latest(args: Dict[str, Any], **_kw: Any) -> str:
    job_id = (args.get("job_id") or "").strip()
    if not job_id:
        return tool_error("job_id is required")

    from social_video_factory import config, media, pipeline
    from social_video_factory.store import JobStore

    store = JobStore()
    try:
        job = store.load(job_id)
    except FileNotFoundError:
        return tool_error(f"job not found: {job_id}", job_id=job_id)

    downloads = config.downloads_dir()
    latest = media.find_latest_download(downloads)
    if latest is None:
        return tool_error(
            f"no video download found in {downloads}", job_id=job_id
        )

    pipeline.run_import(job, store, src_path=latest)
    pipeline.finish_after_import(job, store)

    reloaded = store.load(job.id)
    return json.dumps(reloaded.to_dict(), ensure_ascii=False)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


# NOTE: each tool is registered with a LITERAL top-level ``registry.register(...)``
# call so ``tools/registry.py::discover_builtin_tools`` (which AST-scans module
# bodies for exactly that call shape) auto-imports this module.

registry.register(
    name="social_video_factory_browser_login",
    toolset=_TOOLSET,
    schema=_LOGIN_SCHEMA,
    handler=_handle_browser_login,
    check_fn=_svf_available,
    requires_env=[],
    is_async=False,
    emoji="🔐",
)

registry.register(
    name="social_video_factory_browser_generate_job",
    toolset=_TOOLSET,
    schema=_GENERATE_SCHEMA,
    handler=_handle_browser_generate_job,
    check_fn=_svf_available,
    requires_env=[],
    is_async=False,
    emoji="🎬",
)

registry.register(
    name="social_video_factory_browser_run_queue",
    toolset=_TOOLSET,
    schema=_RUN_QUEUE_SCHEMA,
    handler=_handle_browser_run_queue,
    check_fn=_svf_available,
    requires_env=[],
    is_async=False,
    emoji="🎬",
)

registry.register(
    name="social_video_factory_import_latest_browser_download",
    toolset=_TOOLSET,
    schema=_IMPORT_SCHEMA,
    handler=_handle_import_latest,
    check_fn=_svf_available,
    requires_env=[],
    is_async=False,
    emoji="📥",
)
