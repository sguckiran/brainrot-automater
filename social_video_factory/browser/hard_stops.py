"""Hard-stop detection — scan page text for blocking / forbidden screens.

WHY this module exists: the worker is CONSERVATIVE.  On any screen that asks for
login, presents a CAPTCHA, warns about suspicious activity, announces a rate /
usage limit, pushes an upgrade / payment, refuses on safety / content-policy
grounds, demands age / identity verification, starts an account-recovery flow,
or throws up a consent / policy modal, the worker must STOP, screenshot, mark the
job ``needs_human`` and exit cleanly.  It NEVER tries to solve, bypass, or work
around any of these.

This module is intentionally PURE and Playwright-free: it takes already-extracted
page text (HTML or visible text) and a parsed selector-config dict, and returns
the first matching hard-stop key.  That makes it trivially unit-testable on
canned strings.

Pattern source = the YAML ``hard_stops`` map (user override or bundled example)
MERGED OVER a built-in default set of robust English phrases defined here, so
detection still works even if a user's YAML omits a whole category.
"""

from __future__ import annotations

from typing import Any

from social_video_factory.browser.selectors import load_selector_config

# Ordered tuple of every hard-stop category we recognise.  Order matters: it is
# the priority order ``detect_hard_stop`` reports in (most security-relevant /
# unambiguous first).  Exposed for callers + tests.
HARD_STOP_KEYS: tuple[str, ...] = (
    "login",
    "captcha",
    "suspicious_activity",
    "rate_limit",
    "subscription_upgrade",
    "payment",
    "safety_refusal",
    "content_policy",
    "age_identity_verification",
    "account_recovery",
    "consent_policy_modal",
)

# Built-in default phrases — robust, lower-cased English substrings.  These are
# the safety net so a stale / partial user YAML can never silently disable a
# whole category of hard stop.  Kept lower-case because matching is done against
# lower-cased page text.
_DEFAULT_PATTERNS: dict[str, tuple[str, ...]] = {
    "login": (
        "sign in",
        "log in",
        "sign in to continue",
        "please sign in",
        "you need to sign in",
    ),
    "captcha": (
        "i'm not a robot",
        "verify you are human",
        "verify you're human",
        "recaptcha",
        "captcha",
        "are you a robot",
    ),
    "suspicious_activity": (
        "unusual activity",
        "suspicious activity",
        "we've detected unusual traffic",
        "unusual traffic",
        "automated queries",
    ),
    "rate_limit": (
        "rate limit",
        "usage limit",
        "too many requests",
        "try again later",
        "you've reached your limit",
        "quota exceeded",
    ),
    "subscription_upgrade": (
        "upgrade your plan",
        "subscribe to continue",
        "upgrade to continue",
        "get a subscription",
    ),
    "payment": (
        "add a payment method",
        "payment method",
        "billing",
        "enter your card",
        "update your payment",
    ),
    "safety_refusal": (
        "i can't help with that",
        "i cannot help with that",
        "cannot generate",
        "can't generate",
        "violates our policies",
        "i'm not able to create",
    ),
    "content_policy": (
        "content policy",
        "policy violation",
        "prohibited content",
        "against our guidelines",
    ),
    "age_identity_verification": (
        "verify your age",
        "verify your identity",
        "age verification",
        "identity verification",
        "confirm your age",
    ),
    "account_recovery": (
        "recover your account",
        "account recovery",
        "secure your account",
        "verify it's you",
    ),
    "consent_policy_modal": (
        "before you continue",
        "accept all",
        "i agree",
        "we use cookies",
    ),
}


def _patterns_for(key: str, config: dict[str, Any] | None) -> tuple[str, ...]:
    """Built-in defaults for ``key`` merged with any from the YAML ``hard_stops``.

    The user's YAML can only ADD phrases (or restate existing ones); it can never
    remove a built-in default, so a category cannot be silently disabled.  All
    patterns are lower-cased for case-insensitive substring matching.
    """
    patterns: list[str] = [p.lower() for p in _DEFAULT_PATTERNS.get(key, ())]
    if config:
        hard_stops = config.get("hard_stops") or {}
        user = hard_stops.get(key)
        if isinstance(user, str):
            user = [user]
        if isinstance(user, (list, tuple)):
            for raw in user:
                if raw:
                    patterns.append(str(raw).lower())
    return tuple(patterns)


def detect_hard_stop(page_text: str, config: dict[str, Any] | None = None) -> str | None:
    """Return the first hard-stop key whose any pattern is in ``page_text``.

    PURE: lower-cases ``page_text`` once, then checks each category in
    :data:`HARD_STOP_KEYS` order.  Returns the matching key, or ``None`` when the
    page looks clean.  ``config`` defaults to the loaded selector config when
    omitted, so callers can pass ``None`` and still get YAML-merged patterns.

    This function NEVER acts on a match — detection only.  The worker decides
    what to do (always: stop + needs_human).
    """
    if not page_text:
        return None
    if config is None:
        config = load_selector_config()
    haystack = page_text.lower()
    for key in HARD_STOP_KEYS:
        for pattern in _patterns_for(key, config):
            if pattern and pattern in haystack:
                return key
    return None
