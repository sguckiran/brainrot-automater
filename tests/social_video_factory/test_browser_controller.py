"""Browser controller: fallback, lazy import, and the NO-stealth guarantee.

No real Playwright, no browser launch, no network. We force the lazy import to
fail and assert the controller degrades to clean BrowserUnavailable errors.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from social_video_factory.browser import controller as ctrl
from social_video_factory.browser.controller import (
    REMEDIATION,
    BrowserUnavailable,
    NullController,
    PlaywrightController,
    get_controller,
)


@pytest.fixture(autouse=True)
def _tmp_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SOCIAL_FACTORY_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def test_remediation_mentions_both_install_steps():
    # pip can install the package but not the browser binary — both must show.
    assert "pip install playwright" in REMEDIATION
    assert "playwright install chromium" in REMEDIATION


def test_null_controller_methods_raise_with_remediation():
    null = NullController()
    methods = [
        lambda: null.start(),
        lambda: null.goto("https://example.com"),
        lambda: null.page,
        lambda: null.screenshot("x.png"),
        lambda: null.html(),
        lambda: null.expect_download(lambda: None),
        lambda: null.wait_for_enter("hi"),
    ]
    for call in methods:
        with pytest.raises(BrowserUnavailable) as exc:
            call()
        assert "playwright install chromium" in str(exc.value)
    # close() on a null controller is a harmless no-op.
    assert null.close() is None


def test_get_controller_returns_null_when_playwright_absent(monkeypatch):
    monkeypatch.setattr(ctrl, "_playwright_importable", lambda: False)
    assert isinstance(get_controller(), NullController)


def test_get_controller_returns_playwright_when_importable(monkeypatch):
    monkeypatch.setattr(ctrl, "_playwright_importable", lambda: True)
    assert isinstance(get_controller(), PlaywrightController)


def test_playwright_controller_does_not_import_at_construction(monkeypatch):
    # Make any attempt to lazy-ensure blow up; construction must NOT trigger it.
    def _boom(*_a, **_k):
        raise AssertionError("playwright must not be imported at construction")

    monkeypatch.setattr(PlaywrightController, "_ensure_playwright", _boom)
    pc = PlaywrightController()  # must not raise
    assert pc._context is None
    assert pc._page is None
    # Accessing .page before start() is a clean BrowserUnavailable, not a crash.
    with pytest.raises(BrowserUnavailable):
        _ = pc.page


def test_start_raises_browser_unavailable_when_lazy_import_fails(monkeypatch):
    pc = PlaywrightController()

    def _fail(self):
        raise BrowserUnavailable("playwright import failed: simulated")

    monkeypatch.setattr(PlaywrightController, "_ensure_playwright", _fail)
    with pytest.raises(BrowserUnavailable) as exc:
        pc.start()
    assert "playwright install chromium" in str(exc.value)


def test_context_manager_uses_start_and_close(monkeypatch):
    events = []

    class _Fake(NullController):
        def start(self):
            events.append("start")

        def close(self):
            events.append("close")

    with _Fake() as c:
        assert isinstance(c, _Fake)
    assert events == ["start", "close"]


def _strip_comments_and_docstrings(src: str) -> str:
    """Return only executable code text via the tokenizer.

    Drops comments and string literals (incl. docstrings) so the stealth-flag
    grep below inspects what the module actually *does*, not what its safety
    comments explain it deliberately does NOT do.
    """
    import io
    import token
    import tokenize

    out = []
    tokens = tokenize.generate_tokens(io.StringIO(src).readline)
    for tok in tokens:
        if tok.type in (token.COMMENT, token.STRING):
            continue
        out.append(tok.string)
    return " ".join(out)


def test_no_stealth_flags_in_module_source():
    # Hard safety guarantee: the browser controller must contain NO stealth /
    # anti-detection / fingerprint-spoofing flags in EXECUTABLE code. The words
    # are allowed inside the safety docstring (which explains what we omit), so
    # we tokenize away comments + string literals before grepping.
    src = Path(ctrl.__file__).read_text(encoding="utf-8")
    code = _strip_comments_and_docstrings(src)
    banned = [
        "AutomationControlled",
        "disable-blink-features",
        "webdriver",
        "stealth",
        "fingerprint",
    ]
    for needle in banned:
        assert needle not in code, f"forbidden stealth token in code: {needle!r}"
    # And we never pass launch args at all (no args=[...] in code).
    assert "args" not in code, "launch must pass NO args (no stealth flags)"
