"""Browser controller abstraction + a Playwright-backed implementation.

The controller is a deliberately small, synchronous surface over a single
persistent, headed Chromium profile.  Everything downstream (Phase 3 worker,
the selector resolver) talks to a :class:`BrowserController`, never to
Playwright directly, so the rest of the package stays testable with a fake.

HARD SAFETY CONTRACT (also in ``browser/__init__.py`` and the master plan):
    This module launches Chromium with NO stealth / anti-detection / fingerprint
    -spoofing arguments.  In particular it does NOT pass
    ``--disable-blink-features=AutomationControlled`` (which the in-repo
    ``plugins/google_meet/meet_bot.py`` precedent uses — we deliberately OMIT
    it).  We pass NO ``args=[...]`` at all.  There is a test that greps this
    source for stealth flags; keep it that way.

WHY lazy import: Playwright is an optional, heavy dependency that is NOT
installed by default and whose browser binary cannot be fetched by ``pip``.
:class:`PlaywrightController` therefore imports Playwright only inside
:meth:`PlaywrightController.start`, via :func:`tools.lazy_deps.ensure`, and
turns any failure into a clear :class:`BrowserUnavailable` with remediation.
This also keeps the package importable (for tests / mock mode) without the
Hermes ``tools`` tree or Playwright present.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from social_video_factory import config

# Feature key registered in ``tools/lazy_deps.py`` (Phase 2 packaging).
LAZY_FEATURE = "social_video_factory.browser"

# The single remediation message shown whenever the browser cannot be used.
# pip can install the playwright package but CANNOT fetch the Chromium binary,
# so we always tell the user about the separate ``playwright install`` step.
REMEDIATION = (
    "Playwright is required for browser_flow mode but is unavailable. "
    "Install it with:\n"
    "    pip install playwright\n"
    "    python -m playwright install chromium\n"
    "(the second command downloads the Chromium binary, which pip cannot fetch)."
)


class BrowserUnavailable(RuntimeError):
    """Raised when the browser cannot be launched / used.

    Its message always carries the remediation steps so the CLI can print it
    verbatim and exit cleanly.
    """

    def __init__(self, detail: str | None = None) -> None:
        message = REMEDIATION if not detail else f"{detail}\n\n{REMEDIATION}"
        super().__init__(message)


class BrowserController:
    """Abstract base: a single persistent, headed browser + one page.

    The contract is synchronous on purpose (the login/generate/download flow is
    inherently sequential and human-paced).  Subclasses implement the real
    behaviour; the rest of the package depends only on this surface.
    """

    def start(self) -> None:
        """Launch and hold a browser + page."""
        raise NotImplementedError

    def goto(
        self,
        url: str,
        *,
        wait_until: str = "domcontentloaded",
        timeout_ms: int = 30000,
    ) -> None:
        """Navigate the held page to ``url``."""
        raise NotImplementedError

    @property
    def page(self) -> Any:
        """The underlying page object (used by the worker + selectors)."""
        raise NotImplementedError

    def screenshot(self, path: str | Path) -> Path | None:
        """Save a screenshot to ``path``; return the path or ``None`` on failure."""
        raise NotImplementedError

    def html(self) -> str:
        """Return the full page HTML (for redacted snapshots)."""
        raise NotImplementedError

    def visible_text(self) -> str:
        """Return the page's VISIBLE text (preferred for hard-stop scans).

        Full HTML contains hidden menus, aria labels, footers and inlined
        scripts whose incidental text ("Sign in to another account", "Billing",
        cookie notices) would false-trip the conservative hard-stop detector.
        Scanning only the rendered/visible text keeps detection focused on what
        the user actually sees on screen.
        """
        raise NotImplementedError

    def expect_download(
        self, trigger: Callable[[], None], timeout_ms: int = 120000
    ) -> Path:
        """Run ``trigger`` and capture the resulting download to the downloads dir.

        Returns the saved file path.
        """
        raise NotImplementedError

    def wait_for_enter(self, message: str) -> None:
        """Print ``message`` and block on ``input()`` (login / manual pause)."""
        raise NotImplementedError

    def close(self) -> None:
        """Tear down the browser; safe to call more than once."""
        raise NotImplementedError

    # Context-manager sugar so callers can ``with get_controller() as c:``.
    def __enter__(self) -> "BrowserController":
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


class PlaywrightController(BrowserController):
    """A :class:`BrowserController` backed by ``playwright.sync_api``.

    Mirrors the in-repo precedent ``plugins/google_meet/meet_bot.py`` BUT:
      * uses ``chromium.launch_persistent_context`` (persistent profile) so the
        user's manual login is captured on disk and reused — our code never
        touches cookies / tokens;
      * is HEADED by default (the real generation engine wants a visible UI);
      * passes NO launch ``args`` — explicitly NO stealth / AutomationControlled
        flags.
    """

    def __init__(self) -> None:
        # All Playwright handles are created lazily in start(); construction is
        # side-effect-free and import-free so get_controller()/tests are cheap.
        self._pw: Any = None
        self._context: Any = None
        self._page: Any = None

    def _ensure_playwright(self) -> Any:
        """Lazy-install + import Playwright, mapping all failures to BrowserUnavailable."""
        try:
            # Imported here (not at module top) so the package stays usable
            # without the Hermes ``tools`` tree or Playwright installed.
            from tools.lazy_deps import FeatureUnavailable, ensure
        except ImportError as exc:  # tools tree absent — still actionable.
            raise BrowserUnavailable(f"lazy-dependency installer unavailable: {exc}") from exc

        try:
            ensure(LAZY_FEATURE, prompt=False)
        except FeatureUnavailable as exc:
            raise BrowserUnavailable(str(exc)) from exc

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserUnavailable(f"playwright import failed: {exc}") from exc
        return sync_playwright

    def start(self) -> None:
        if self._context is not None:
            return
        sync_playwright = self._ensure_playwright()
        try:
            self._pw = sync_playwright().start()
            # NOTE: NO args= here.  No stealth / anti-detection flags.  This is
            # an intentional divergence from meet_bot.py:514 and is asserted by
            # tests/social_video_factory/test_browser_controller.py.
            self._context = self._pw.chromium.launch_persistent_context(
                user_data_dir=str(config.profile_dir()),
                headless=config.browser_headless(),
                accept_downloads=True,
                downloads_path=str(config.downloads_dir()),
                executable_path=config.browser_executable_path() or None,
            )
            pages = self._context.pages
            self._page = pages[0] if pages else self._context.new_page()
        except BrowserUnavailable:
            raise
        except Exception as exc:  # launch failed (missing binary, etc.)
            self.close()
            raise BrowserUnavailable(f"failed to launch Chromium: {exc}") from exc

    @property
    def page(self) -> Any:
        if self._page is None:
            raise BrowserUnavailable("browser not started — call start() first")
        return self._page

    def goto(
        self,
        url: str,
        *,
        wait_until: str = "domcontentloaded",
        timeout_ms: int = 30000,
    ) -> None:
        self.page.goto(url, wait_until=wait_until, timeout=timeout_ms)

    def screenshot(self, path: str | Path) -> Path | None:
        target = Path(path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(target))
            return target
        except Exception:
            # Screenshots are best-effort diagnostics — never fatal.
            return None

    def html(self) -> str:
        return self.page.content()

    def visible_text(self) -> str:
        """Rendered text of the page body (falls back to full content)."""
        try:
            return self.page.inner_text("body")
        except Exception:
            # body not ready / detached — fall back to full HTML so a scan
            # still has something to look at.
            return self.page.content()

    def expect_download(
        self, trigger: Callable[[], None], timeout_ms: int = 120000
    ) -> Path:
        downloads = config.downloads_dir()
        with self.page.expect_download(timeout=timeout_ms) as download_info:
            trigger()
        download = download_info.value
        target = downloads / download.suggested_filename
        download.save_as(str(target))
        return target

    def wait_for_enter(self, message: str) -> None:
        print(message)
        input()

    def close(self) -> None:
        # Tear down in reverse order; swallow errors so close() is idempotent
        # and safe in __exit__ even after a partial start().
        try:
            if self._context is not None:
                self._context.close()
        except Exception:
            pass
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:
            pass
        self._context = None
        self._page = None
        self._pw = None


class NullController(BrowserController):
    """Fallback used when Playwright clearly cannot be imported.

    Every method raises :class:`BrowserUnavailable` with the remediation text,
    so callers get one clean, actionable error instead of an opaque ImportError
    deep in the flow.  This is the "clean fallback" the master plan calls for.
    """

    def start(self) -> None:
        raise BrowserUnavailable()

    def goto(
        self,
        url: str,
        *,
        wait_until: str = "domcontentloaded",
        timeout_ms: int = 30000,
    ) -> None:
        raise BrowserUnavailable()

    @property
    def page(self) -> Any:
        raise BrowserUnavailable()

    def screenshot(self, path: str | Path) -> Path | None:
        raise BrowserUnavailable()

    def html(self) -> str:
        raise BrowserUnavailable()

    def visible_text(self) -> str:
        raise BrowserUnavailable()

    def expect_download(
        self, trigger: Callable[[], None], timeout_ms: int = 120000
    ) -> Path:
        raise BrowserUnavailable()

    def wait_for_enter(self, message: str) -> None:
        raise BrowserUnavailable()

    def close(self) -> None:
        # Closing a never-started null controller is a harmless no-op.
        return None


def _playwright_importable() -> bool:
    """Cheap check: can the ``playwright`` package be found at all?

    We only test for the module's presence (via importlib.util.find_spec) — we
    do NOT import it and do NOT trigger a lazy install here.  The actual import
    + install is deferred to :meth:`PlaywrightController.start`.  Kept as a
    module-level function so tests can monkeypatch it.
    """
    import importlib.util

    try:
        return importlib.util.find_spec("playwright") is not None
    except (ImportError, ValueError):
        return False


def get_controller() -> BrowserController:
    """Factory: return a usable :class:`BrowserController`.

    Returns a :class:`PlaywrightController` (whose real Playwright import is
    still deferred to ``start()``) when Playwright looks importable, otherwise a
    :class:`NullController` that fails cleanly with remediation.  Note that even
    the PlaywrightController path can still raise :class:`BrowserUnavailable`
    from ``start()`` if the lazy install fails or the Chromium binary is
    missing — the NullController is only the "definitely not here" shortcut.
    """
    if _playwright_importable():
        return PlaywrightController()
    return NullController()
