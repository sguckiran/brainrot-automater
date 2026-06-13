"""Browser layer for social_video_factory.

This subpackage drives the user's OWN logged-in local Chromium profile against
their existing Gemini / Flow subscription.  It is the real generation engine for
the ``browser_flow`` mode.

HARD SAFETY CONTRACT (enforced in code + tests, see the master plan):
    NO stealth, NO fingerprint spoofing, NO anti-detection launch flags (in
    particular NO ``--disable-blink-features=AutomationControlled``), NO CAPTCHA
    solving, NO proxy / account rotation, NO bypass of login / usage limits /
    safety refusals.  The browser only ever drives the user's own session in a
    persistent, headed profile.

Phase 2 ships the controller abstraction + layered selector resolution + the
``browser-login`` CLI command.  The worker / hard-stops / rate-limit live in
later phases.
"""

from __future__ import annotations

from social_video_factory.browser.artifacts import ArtifactLogger, redact
from social_video_factory.browser.controller import (
    BrowserController,
    BrowserUnavailable,
    NullController,
    PlaywrightController,
    get_controller,
)
from social_video_factory.browser.hard_stops import (
    HARD_STOP_KEYS,
    detect_hard_stop,
)
from social_video_factory.browser.queue import (
    QueueResult,
    run_queue,
)
from social_video_factory.browser.selectors import SelectorResolver
from social_video_factory.browser.worker import (
    GenerationOutcome,
    generate_in_browser,
)

__all__ = [
    "BrowserController",
    "BrowserUnavailable",
    "NullController",
    "PlaywrightController",
    "get_controller",
    "SelectorResolver",
    "ArtifactLogger",
    "redact",
    "HARD_STOP_KEYS",
    "detect_hard_stop",
    "GenerationOutcome",
    "generate_in_browser",
    "QueueResult",
    "run_queue",
]
