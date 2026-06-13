"""Hard-stop detection on canned text — pure, no Playwright."""

from __future__ import annotations

import pytest

from social_video_factory.browser.hard_stops import (
    HARD_STOP_KEYS,
    detect_hard_stop,
)

# One canned snippet per category that should trigger the built-in defaults.
_CANNED = {
    "login": "<html><body>Please sign in to continue</body></html>",
    "captcha": "Verify you are human — reCAPTCHA challenge",
    "suspicious_activity": "We've detected unusual traffic from your network",
    "rate_limit": "Too many requests, please try again later",
    "subscription_upgrade": "Upgrade your plan to keep generating",
    "payment": "Please add a payment method to continue",
    "safety_refusal": "I can't help with that request",
    "content_policy": "This violates our content policy",
    "age_identity_verification": "We need to verify your age before continuing",
    "account_recovery": "Let's recover your account",
    "consent_policy_modal": "Before you continue to Google Labs",
}


@pytest.mark.parametrize("key", HARD_STOP_KEYS)
def test_each_category_detected(key):
    assert key in _CANNED, f"no canned snippet for {key}"
    # config={} → built-in defaults only (proves defaults work without YAML).
    assert detect_hard_stop(_CANNED[key], {}) == key


def test_clean_page_returns_none():
    clean = "<html><body>Your video is ready. Enjoy your creation!</body></html>"
    assert detect_hard_stop(clean, {}) is None


def test_empty_text_returns_none():
    assert detect_hard_stop("", {}) is None
    assert detect_hard_stop("", None) is None


def test_user_yaml_pattern_merges_with_defaults():
    cfg = {"hard_stops": {"rate_limit": ["custom quota wall"]}}
    # Custom phrase is detected...
    assert detect_hard_stop("you hit the custom quota wall", cfg) == "rate_limit"
    # ...and a built-in default for the SAME category still works (not replaced).
    assert detect_hard_stop("too many requests", cfg) == "rate_limit"
    # A default for a DIFFERENT category the YAML didn't mention still works.
    assert detect_hard_stop("please sign in", cfg) == "login"


def test_priority_order_login_before_consent():
    # A page with both a login phrase and a consent phrase reports login first.
    text = "Please sign in. Before you continue to Google Labs."
    assert detect_hard_stop(text, {}) == "login"


def test_case_insensitive():
    assert detect_hard_stop("PLEASE SIGN IN TO CONTINUE", {}) == "login"


def test_benign_cookie_banner_does_not_trip():
    # A routine cookie banner is NOT a hard stop — it appears on nearly every
    # Google page and must not halt every run. This is the false-positive the
    # tightened consent patterns + visible-text scan are designed to avoid.
    banner = (
        "We use cookies and data to deliver and maintain Google services. "
        "Accept all. Reject all. I agree."
    )
    assert detect_hard_stop(banner, {}) is None


def test_incidental_signin_word_does_not_trip():
    # A logged-in page whose account menu contains "Sign in to another account"
    # must not be mistaken for a login wall.
    page = "Your video is ready. Account menu: Sign in to another account."
    assert detect_hard_stop(page, {}) is None
