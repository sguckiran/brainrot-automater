"""Selector resolution + manual-pause fallback against a FAKE page.

No real Playwright. The fake page is a duck-typed object whose query_selector /
get_by_role / get_by_label / get_by_text are stubs we control per test.
"""

from __future__ import annotations

import pytest

from social_video_factory.browser import selectors as sel
from social_video_factory.browser.selectors import (
    ACTION_KEYS,
    SelectorResolver,
    load_selector_config,
)


@pytest.fixture(autouse=True)
def _tmp_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SOCIAL_FACTORY_DATA_DIR", str(tmp_path / "data"))
    # Force the bundled example (no user override).
    monkeypatch.setenv("SOCIAL_FACTORY_SELECTORS_FILE", "")
    # Clear the parse cache so each test reads fresh.
    sel._parse_yaml.cache_clear()
    return tmp_path


class FakePage:
    """Duck-typed page; each finder returns whatever we set, recording calls."""

    def __init__(
        self,
        css_hits=None,
        role_hit=None,
        label_hit=None,
        text_hit=None,
    ):
        self.css_hits = css_hits or {}  # selector -> result
        self.role_hit = role_hit
        self.label_hit = label_hit
        self.text_hit = text_hit
        self.calls = []

    def query_selector(self, selector):
        self.calls.append(("query_selector", selector))
        return self.css_hits.get(selector)

    def get_by_role(self, role, **kwargs):
        self.calls.append(("get_by_role", role, kwargs))
        return self.role_hit

    def get_by_label(self, label):
        self.calls.append(("get_by_label", label))
        return self.label_hit

    def get_by_text(self, text):
        self.calls.append(("get_by_text", text))
        return self.text_hit


class FakeController:
    """Records wait_for_enter and screenshot calls; no browser."""

    def __init__(self):
        self.entered = []
        self.shots = []

    def wait_for_enter(self, message):
        self.entered.append(message)

    def screenshot(self, path):
        self.shots.append(path)
        return None  # simulate best-effort failure


# --- bundled YAML --------------------------------------------------------


def test_bundled_example_parses_and_has_documented_keys():
    cfg = load_selector_config()
    for target in ("flow", "gemini"):
        assert target in cfg, target
        for action in ACTION_KEYS:
            assert action in cfg[target], f"{target}.{action}"
    hard_stops = cfg["hard_stops"]
    for key in (
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
    ):
        assert key in hard_stops, key


def test_user_override_file_wins(monkeypatch, tmp_path):
    override = tmp_path / "mine.yaml"
    override.write_text("flow:\n  submit:\n    css: ['#mine']\n", encoding="utf-8")
    monkeypatch.setenv("SOCIAL_FACTORY_SELECTORS_FILE", str(override))
    sel._parse_yaml.cache_clear()
    cfg = load_selector_config()
    assert cfg["flow"]["submit"]["css"] == ["#mine"]


# --- layered resolution --------------------------------------------------


def test_configured_css_hit_wins_first():
    # Use whatever the bundled config's FIRST flow.submit css selector is, so
    # this test isn't coupled to a specific (tunable) selector string.
    cfg = load_selector_config()
    first_css = cfg["flow"]["submit"]["css"][0]
    page = FakePage(css_hits={first_css: "CSS_NODE"})
    resolver = SelectorResolver(page, cfg, "flow", FakeController())
    assert resolver.locate("submit") == "CSS_NODE"
    # It stopped at the first css and never reached role/label/text.
    assert all(c[0] == "query_selector" for c in page.calls)


def test_falls_back_to_role_when_no_css():
    page = FakePage(css_hits={}, role_hit="ROLE_NODE")
    resolver = SelectorResolver(page, load_selector_config(), "flow", FakeController())
    assert resolver.locate("submit") == "ROLE_NODE"
    assert any(c[0] == "get_by_role" for c in page.calls)


def test_falls_back_to_text_when_no_css_or_role():
    page = FakePage(css_hits={}, role_hit=None, label_hit=None, text_hit="TEXT_NODE")
    resolver = SelectorResolver(page, load_selector_config(), "flow", FakeController())
    assert resolver.locate("submit") == "TEXT_NODE"
    assert any(c[0] == "get_by_text" for c in page.calls)


def test_locate_returns_none_when_nothing_matches():
    page = FakePage(css_hits={}, role_hit=None, label_hit=None, text_hit=None)
    resolver = SelectorResolver(page, load_selector_config(), "flow", FakeController())
    assert resolver.locate("submit") is None


def test_manual_pause_calls_wait_for_enter_and_returns_none():
    controller = FakeController()
    page = FakePage()
    resolver = SelectorResolver(page, load_selector_config(), "flow", controller)
    result = resolver.manual_pause("could not find the download button")
    assert result is None
    assert len(controller.entered) == 1
    assert "could not find the download button" in controller.entered[0]
    # Best-effort screenshot was attempted.
    assert controller.shots
