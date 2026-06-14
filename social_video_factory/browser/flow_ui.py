"""Current Google Flow UI adapter.

Flow has a project-list landing page and a Slate-based composer inside each
project. Generated media cards link to a detail page where Download lives.
Keep those transitions here so the generic resolver remains useful elsewhere.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin


class FlowUIError(RuntimeError):
    """Raised when the expected Flow workspace contract is unavailable."""


@dataclass
class PreparedFlowGeneration:
    """Controls and baseline state needed to submit one Flow generation."""

    prompt_box: Any
    submit: Any
    baseline_edit_urls: frozenset[str]


def _button_text(button: Any) -> str:
    try:
        return " ".join((button.inner_text() or "").split())
    except Exception:
        return ""


def _is_enabled(button: Any) -> bool:
    """Best-effort enabled check that tolerates fakes lacking is_enabled."""
    try:
        return button.is_enabled()
    except AttributeError:
        try:
            return not button.is_disabled()
        except Exception:
            return True
    except Exception:
        return True


def _try_click(button: Any, *, timeout_ms: int = 8000) -> bool:
    """Click with a BOUNDED timeout. Returns success; never hangs ~30s or raises.

    The blind ``locator.click()`` default is a 30s action timeout, so a single
    disabled/re-rendering control would stall (and crash) the whole unattended
    run. We bound it and report success/failure so callers decide what's fatal.
    """
    try:
        try:
            button.click(timeout=timeout_ms)
        except TypeError:
            # Test doubles' click() takes no timeout kwarg.
            button.click()
        return True
    except Exception:
        return False


def _find_button(page: Any, predicate: Any) -> Any | None:
    buttons = page.locator("button")
    for index in range(buttons.count()):
        button = buttons.nth(index)
        if predicate(_button_text(button)):
            return button
    return None


def _wait_for(getter: Any, *, timeout_s: float, poll_s: float = 0.5) -> Any | None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        value = getter()
        if value is not None:
            return value
        time.sleep(poll_s)
    return None


def _visible(locator: Any) -> bool:
    try:
        return locator.is_visible()
    except Exception:
        return True


def _dismiss_cookie_banner(page: Any) -> None:
    """Dismiss Flow's ordinary optional-cookie banner when present."""
    button = _find_button(page, lambda text: text == "No thanks")
    if button is not None and _visible(button):
        _try_click(button)


def _prompt_box(page: Any) -> Any | None:
    locator = page.locator("div[contenteditable='true'][role='textbox']")
    try:
        if locator.count() and _visible(locator.first):
            return locator.first
    except Exception:
        return None
    return None


def _project_links(page: Any) -> list[str]:
    links = page.locator("a[href*='/fx/tools/flow/project/']")
    result: list[str] = []
    try:
        for index in range(links.count()):
            href = links.nth(index).get_attribute("href")
            if href and "/edit/" not in href:
                result.append(href)
    except Exception:
        return []
    return result


def _result_edit_urls(page: Any) -> set[str]:
    """Return current generated-result detail URLs for the open project."""
    links = page.locator("a[href*='/edit/']")
    result: set[str] = set()
    try:
        for index in range(links.count()):
            href = links.nth(index).get_attribute("href")
            if href:
                result.add(urljoin(page.url, href))
    except Exception:
        return set()
    return result


def _open_fresh_project(page: Any, flow_url: str, *, timeout_s: float) -> None:
    if "/fx/tools/flow/project/" in (getattr(page, "url", "") or ""):
        return

    _dismiss_cookie_banner(page)
    existing = set(_project_links(page))
    new_project = _wait_for(
        lambda: _find_button(page, lambda text: text.endswith("New project")),
        timeout_s=timeout_s,
    )
    if new_project is None:
        raise FlowUIError("Flow's New project control did not appear")
    if not _try_click(new_project):
        raise FlowUIError("Flow's New project control could not be clicked")

    def _opened_project() -> tuple[str, str | None] | None:
        if (
            "/fx/tools/flow/project/" in (getattr(page, "url", "") or "")
            or _prompt_box(page) is not None
        ):
            return ("direct", None)
        links = _project_links(page)
        href = next((value for value in links if value not in existing), None)
        return ("link", href) if href else None

    opened = _wait_for(_opened_project, timeout_s=timeout_s)
    if opened is None:
        raise FlowUIError("Flow did not open or create a project")
    mode, href = opened
    if mode == "link" and href:
        page.goto(urljoin(flow_url, href), wait_until="domcontentloaded", timeout=30000)


def _composer_summary(page: Any) -> Any | None:
    return _find_button(
        page,
        lambda text: text.startswith("Video ")
        or text.startswith("Video\u00b7")
        or "Nano Banana" in text,
    )


def _setting_button(page: Any, label: str) -> Any | None:
    return _find_button(page, lambda text: text == label)


def _activate_setting(page: Any, label: str) -> None:
    """Best-effort toggle of a composer setting.

    The Flow composer already defaults to Video / 9:16 / 1x / 8s, so this is a
    confirmation, not a hard requirement. We NEVER raise or hang here: a missing
    or momentarily-disabled toggle is skipped, leaving the (correct) default in
    place, rather than crashing the whole unattended run on a 30s click timeout.
    """
    button = _setting_button(page, label)
    if button is None:
        return
    try:
        active = button.get_attribute("data-state") == "active"
    except Exception:
        active = False
    if active or not _is_enabled(button):
        return
    _try_click(button)
    time.sleep(0.5)


def _enabled_submit(page: Any, *, find_timeout_s: float, enable_timeout_s: float) -> Any | None:
    """Find the Create button and return it once enabled, else None."""
    submit = _wait_for(
        lambda: _find_button(page, lambda text: text == "arrow_forward Create"),
        timeout_s=find_timeout_s,
    )
    if submit is None:
        return None
    return _wait_for(
        lambda: submit if _is_enabled(submit) else None,
        timeout_s=enable_timeout_s,
    )


def _enter_prompt(page: Any, prompt_box: Any, prompt: str, *, timeout_s: float) -> Any | None:
    """Type the prompt and return the ENABLED Create button (or None).

    Flow's prompt box is a Slate ``contenteditable``. Before it has fully
    hydrated, ``.fill()`` can silently no-op, leaving Create disabled — an
    intermittent race that crashed unattended runs. So we try focus+fill first,
    then fall back to real keystroke typing (which Slate always reacts to),
    waiting for Create to enable after each attempt.
    """
    try:
        prompt_box.click()
    except Exception:
        pass
    try:
        prompt_box.fill(prompt)
    except Exception:
        pass
    submit = _enabled_submit(page, find_timeout_s=timeout_s, enable_timeout_s=8)
    if submit is not None:
        return submit

    # Fallback: clear + type character-by-character so Slate's input handlers fire.
    for _ in range(2):
        try:
            prompt_box.click()
            try:
                prompt_box.fill("")
            except Exception:
                pass
            typer = getattr(prompt_box, "press_sequentially", None) or getattr(
                prompt_box, "type", None
            )
            if typer is not None:
                typer(prompt)
        except Exception:
            pass
        submit = _enabled_submit(page, find_timeout_s=timeout_s, enable_timeout_s=10)
        if submit is not None:
            return submit
    return None


def prepare_generation(
    page: Any,
    flow_url: str,
    prompt: str,
    *,
    timeout_s: float = 60,
) -> PreparedFlowGeneration:
    """Open a fresh project and prepare one portrait video generation."""
    _open_fresh_project(page, flow_url, timeout_s=timeout_s)
    prompt_box = _wait_for(lambda: _prompt_box(page), timeout_s=timeout_s)
    if prompt_box is None:
        raise FlowUIError("Flow's prompt editor did not appear")

    # Confirm the portrait-video defaults. This whole block is BEST-EFFORT:
    # Flow already defaults to Video / 9:16 / 1x / 8s, and a flaky settings
    # interaction must never crash or hang the unattended run. If anything here
    # misbehaves we simply proceed with the (correct) defaults.
    summary = _wait_for(lambda: _composer_summary(page), timeout_s=timeout_s)
    if summary is not None:
        try:
            _try_click(summary)  # expand
            time.sleep(0.5)
            _activate_setting(page, "play_circle Video")
            _activate_setting(page, "crop_9_16 9:16")
            _activate_setting(page, "1x")
            summary = _composer_summary(page)
            if summary is not None and summary.get_attribute("data-state") == "open":
                _try_click(summary)  # collapse
        except Exception:
            pass

    submit = _enter_prompt(page, prompt_box, prompt, timeout_s=timeout_s)
    if submit is None:
        raise FlowUIError("Flow's Create submit control stayed disabled after the prompt")

    return PreparedFlowGeneration(
        prompt_box=prompt_box,
        submit=submit,
        baseline_edit_urls=frozenset(_result_edit_urls(page)),
    )


def new_result_edit_url(
    page: Any,
    baseline_edit_urls: frozenset[str] | set[str],
) -> str | None:
    """Return the detail URL once a new generated video card appears."""
    current = _result_edit_urls(page)
    return next(iter(current - set(baseline_edit_urls)), None)


def download_from_detail(
    controller: Any,
    edit_url: str,
    *,
    timeout_s: float = 300,
) -> Any:
    """Open a generated video's detail page and capture its download.

    The result's ``/edit/`` URL appears as soon as generation is SUBMITTED, so a
    caller can reach here while the clip is still rendering. We therefore wait
    for the Download control to be present AND ENABLED (which only happens once
    the video is ready) before clicking. This both lets a too-early call wait
    out the render and avoids a blind 30s click on a disabled button crashing
    the run.
    """
    controller.goto(edit_url)

    def _ready_download() -> Any | None:
        button = _find_button(
            controller.page,
            lambda text: text == "download Download",
        )
        if button is not None and _is_enabled(button):
            return button
        return None

    download = _wait_for(_ready_download, timeout_s=timeout_s, poll_s=2)
    if download is None:
        raise FlowUIError("Flow's Download control did not become ready")
    # Plain click (default action timeout): a download-triggering click needs
    # longer than a short bounded click for Playwright to settle the download.
    return controller.expect_download(trigger=download.click)
