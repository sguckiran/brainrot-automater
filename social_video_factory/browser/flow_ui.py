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
        button.click()


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
    new_project.click()

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
    button = _setting_button(page, label)
    if button is None:
        raise FlowUIError(f"Flow setting not found: {label}")
    try:
        active = button.get_attribute("data-state") == "active"
    except Exception:
        active = False
    if not active:
        button.click()
        time.sleep(0.5)


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

    summary = _wait_for(lambda: _composer_summary(page), timeout_s=timeout_s)
    if summary is None:
        raise FlowUIError("Flow's generation settings did not appear")
    summary.click()

    _activate_setting(page, "play_circle Video")
    _activate_setting(page, "crop_9_16 9:16")
    _activate_setting(page, "1x")

    summary = _composer_summary(page)
    if summary is not None:
        try:
            if summary.get_attribute("data-state") == "open":
                summary.click()
        except Exception:
            pass

    prompt_box.fill(prompt)
    submit = _find_button(page, lambda text: text == "arrow_forward Create")
    if submit is None:
        raise FlowUIError("Flow's Create submit control did not appear")
    try:
        if submit.is_disabled():
            raise FlowUIError("Flow's Create submit control stayed disabled")
    except AttributeError:
        pass

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
    timeout_s: float = 60,
) -> Any:
    """Open a generated video's detail page and capture its download."""
    controller.goto(edit_url)
    download = _wait_for(
        lambda: _find_button(
            controller.page,
            lambda text: text == "download Download",
        ),
        timeout_s=timeout_s,
    )
    if download is None:
        raise FlowUIError("Flow's video Download control did not appear")
    return controller.expect_download(trigger=download.click)
