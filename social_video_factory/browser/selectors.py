"""Layered, resilient selector resolution for the Gemini / Flow web UIs.

Web UIs change often, so we NEVER rely on a single brittle CSS selector.  For
each UI action (``prompt_box``, ``submit``, ``download`` ...) we try, in order:

  1. configured CSS / text selectors from the YAML (user override or bundled
     example), tried one at a time;
  2. accessible queries — Playwright ``get_by_role`` / ``get_by_label`` driven
     by ``role`` / ``label`` hints in the YAML;
  3. visible button text — ``get_by_text`` and ``role=button`` with a name;
  4. a MANUAL PAUSE fallback: save a screenshot (best effort), print exactly
     what the human needs to do plus where downloads land, block on Enter, then
     return ``None`` so the caller proceeds from whatever the human just did.

This layering is deliberately pure: it only touches the duck-typed ``page`` and
``controller`` objects, so it unit-tests against fakes with NO real Playwright.

The YAML schema (documented fully in ``browser_selectors.example.yaml``):

    <target>:                 # 'flow' or 'gemini'
      <action_key>:           # prompt_box | submit | generating_indicator |
                              # download | export_mp4 | result_video
        css: [".sel-a", ".sel-b"]   # CSS / text selectors, tried in order
        role: {role: "button", name: "Send"}   # accessible-role hint
        label: "Prompt"                          # accessible-label hint
        text: "Generate"                         # visible-text hint
    hard_stops:               # text patterns reserved for Phase 3 (NOT used here)
      login: [...]
      captcha: [...]
      ...
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from social_video_factory import config

# The bundled example lives next to the package root (sibling of this subpackage).
_EXAMPLE_FILENAME = "browser_selectors.example.yaml"

# Action keys documented in the schema.  Kept here so callers / tests have a
# single source of truth for the supported actions.
ACTION_KEYS = (
    "prompt_box",
    "submit",
    "generating_indicator",
    "download",
    "export_mp4",
    "result_video",
)


def _example_path() -> Path:
    """Path to the bundled ``browser_selectors.example.yaml`` (package root)."""
    return Path(__file__).resolve().parent.parent / _EXAMPLE_FILENAME


@lru_cache(maxsize=8)
def _parse_yaml(path_str: str) -> dict[str, Any]:
    """Parse + cache a selector YAML file.  Cached by absolute path string."""
    with open(path_str, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data or {}


def load_selector_config() -> dict[str, Any]:
    """Load the selector config: user override if set, else the bundled example.

    ``SOCIAL_FACTORY_SELECTORS_FILE`` wins when set and the file exists; missing
    overrides fall back to the bundled example rather than erroring, so a stale
    env var never bricks the flow.
    """
    override = config.selectors_file()
    if override and Path(override).is_file():
        return _parse_yaml(str(Path(override).resolve()))
    return _parse_yaml(str(_example_path()))


class SelectorResolver:
    """Resolve a UI ``action_key`` to a locator using the layered strategy.

    Constructed per target (``flow`` / ``gemini``) with the live ``page`` and
    its owning ``controller`` (used for the manual-pause fallback).
    """

    def __init__(
        self,
        page: Any,
        config_data: dict[str, Any],
        target: str,
        controller: Any,
    ) -> None:
        self.page = page
        self.config = config_data or {}
        self.target = target
        self.controller = controller

    # -- public API ---------------------------------------------------------

    def locate(self, action_key: str) -> Any | None:
        """Return a locator for ``action_key`` or ``None`` if nothing matched.

        Tries configured selectors → accessible role/label → visible text.
        Returns the FIRST hit.  A ``None`` here is the signal for the caller to
        invoke :meth:`manual_pause` (we do not auto-pause inside ``locate`` so
        callers stay in control of when a human is asked to step in).
        """
        spec = self._action_spec(action_key)

        hit = self._try_configured(spec)
        if hit is not None:
            return hit

        hit = self._try_accessible(spec)
        if hit is not None:
            return hit

        hit = self._try_text(spec)
        if hit is not None:
            return hit

        return None

    def manual_pause(self, reason: str) -> None:
        """Save a screenshot (best-effort), tell the human what to do, wait.

        Returns ``None`` so the caller proceeds from whatever state the human
        left the page in.  Never raises on screenshot failure.
        """
        shot_note = ""
        try:
            shot_path = config.logs_dir() / "manual_pause.png"
            saved = self.controller.screenshot(shot_path)
            if saved:
                shot_note = f"\n  screenshot: {saved}"
        except Exception:
            # A failed diagnostic screenshot must never block the human handoff.
            pass

        downloads = config.downloads_dir()
        message = (
            f"\n[manual step needed] {reason}\n"
            f"  Please complete this action in the open browser window."
            f"{shot_note}\n"
            f"  Downloads are saved to: {downloads}\n"
            f"  Press Enter here once done to continue..."
        )
        self.controller.wait_for_enter(message)
        return None

    # -- layers -------------------------------------------------------------

    def _action_spec(self, action_key: str) -> dict[str, Any]:
        """The per-action config block for this target, or ``{}``."""
        target_cfg = self.config.get(self.target) or {}
        spec = target_cfg.get(action_key)
        return spec if isinstance(spec, dict) else {}

    def _try_configured(self, spec: dict[str, Any]) -> Any | None:
        """Layer 1: configured CSS / text selectors, tried in order.

        Each selector is passed to ``page.query_selector``; the first that
        returns a truthy locator wins.  Empty / garbage selectors simply return
        nothing and fall through to the next layer.
        """
        selectors = spec.get("css") or spec.get("selectors") or []
        if isinstance(selectors, str):
            selectors = [selectors]
        for sel in selectors:
            if not sel:
                continue
            try:
                found = self.page.query_selector(sel)
            except Exception:
                found = None
            if found:
                return found
        return None

    def _try_accessible(self, spec: dict[str, Any]) -> Any | None:
        """Layer 2: accessible role / label queries."""
        role = spec.get("role")
        if isinstance(role, dict) and role.get("role"):
            try:
                kwargs = {k: v for k, v in role.items() if k != "role"}
                found = self.page.get_by_role(role["role"], **kwargs)
            except Exception:
                found = None
            if found:
                return found

        label = spec.get("label")
        if label:
            try:
                found = self.page.get_by_label(label)
            except Exception:
                found = None
            if found:
                return found
        return None

    def _try_text(self, spec: dict[str, Any]) -> Any | None:
        """Layer 3: visible button text / get_by_text."""
        text = spec.get("text")
        if not text:
            return None
        try:
            found = self.page.get_by_text(text)
        except Exception:
            found = None
        if found:
            return found
        # Last text attempt: a button named like the text.
        try:
            return self.page.get_by_role("button", name=text) or None
        except Exception:
            return None
