"""Browser-based Instagram and TikTok publishing.

Credentials are never accepted or stored by this module. Each platform uses a
separate persistent browser profile populated by a one-time manual login.
Challenges, verification screens, and selector drift stop for human review.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from social_video_factory import config
from social_video_factory.browser.controller import (
    BrowserController,
    PlaywrightController,
)
from social_video_factory.models import Job, JobStatus
from social_video_factory.store import JobStore

PLATFORM_URLS = {
    "instagram": "https://www.instagram.com/",
    "tiktok": "https://www.tiktok.com/tiktokstudio/upload",
}


class PublishNeedsHuman(RuntimeError):
    """The platform requires login, verification, or selector maintenance."""


def _platform(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in PLATFORM_URLS:
        raise ValueError(f"unsupported platform: {value!r}")
    return normalized


def controller_for(platform: str) -> BrowserController:
    """Create a controller using the platform's isolated persistent profile."""
    return PlaywrightController(profile_path=config.social_profile_dir(_platform(platform)))


def login(platform: str, controller: BrowserController | None = None) -> None:
    """Open a platform profile and wait while the user logs in manually."""
    platform = _platform(platform)
    browser = controller or controller_for(platform)
    try:
        browser.start()
        browser.goto(PLATFORM_URLS[platform], timeout_ms=60000)
        browser.wait_for_enter(
            f"Log in to {platform.title()} in the opened browser. Complete any "
            "verification, confirm the home/upload page is visible, then press "
            "Enter here to save the session."
        )
    finally:
        browser.close()


def _visible(locator: Any) -> bool:
    try:
        return locator.count() > 0 and locator.first.is_visible()
    except Exception:
        return False


def _visible_match(locator: Any) -> Any | None:
    """Return the first visible member of a locator that may include clones."""
    try:
        for index in range(locator.count()):
            candidate = locator.nth(index)
            if candidate.is_visible():
                return candidate
    except Exception:
        return None
    return None


def _first_visible(page: Any, selectors: list[str], timeout_s: float = 20) -> Any:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for selector in selectors:
            locator = page.locator(selector)
            candidate = _visible_match(locator)
            if candidate is not None:
                return candidate
        page.wait_for_timeout(300)
    raise PublishNeedsHuman(
        "The expected control was not found. The platform UI may have changed."
    )


def _role(page: Any, role: str, names: list[str], timeout_s: float = 20) -> Any:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for name in names:
            locator = page.get_by_role(role, name=re.compile(name, re.I))
            if _visible(locator):
                return locator.first
        page.wait_for_timeout(300)
    raise PublishNeedsHuman(
        f"Could not find the expected {role} ({', '.join(names)})."
    )


def _check_blocking_screen(controller: BrowserController, platform: str) -> None:
    text = controller.visible_text().lower()
    page = controller.page
    login_controls = (
        "input[name='username']",
        "input[name='password']",
        "form[action*='login' i]",
    )
    markers = (
        "verify it's you",
        "verify your identity",
        "security check",
        "suspicious activity",
        "captcha",
        "too many attempts",
    )
    if any(_visible(page.locator(selector)) for selector in login_controls) or any(
        marker in text for marker in markers
    ):
        raise PublishNeedsHuman(
            f"{platform.title()} requires login or verification in its saved profile."
        )


def _set_files(page: Any, media_path: Path) -> None:
    file_input = page.locator("input[type='file']")
    try:
        file_input.first.set_input_files(str(media_path), timeout=20000)
    except Exception as exc:
        raise PublishNeedsHuman("Could not find or use the video upload input.") from exc


def _click_if_visible(locator: Any) -> bool:
    if not _visible(locator):
        return False
    locator.first.click()
    return True


def _wait_for_enabled(locator: Any, timeout_s: float = 60) -> Any:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _visible(locator):
            try:
                if locator.first.is_enabled():
                    return locator.first
            except Exception:
                pass
        time.sleep(0.3)
    raise PublishNeedsHuman("The publish control never became ready.")


def _wait_for_publish_result(
    page: Any,
    success_patterns: list[str],
    *,
    timeout_s: float = 120,
    success_url_excludes: str | None = None,
) -> None:
    """Wait for a verified success signal after the final publish click."""
    deadline = time.monotonic() + timeout_s
    combined = re.compile("|".join(success_patterns), re.I)
    while time.monotonic() < deadline:
        try:
            if page.is_closed():
                raise PublishNeedsHuman(
                    "The platform closed the upload page before success was confirmed."
                )
            if success_url_excludes and success_url_excludes not in page.url:
                return
            body = page.locator("body").inner_text(timeout=2000)
            if combined.search(body):
                return
        except PublishNeedsHuman:
            raise
        except Exception:
            pass
        time.sleep(0.5)
    raise PublishNeedsHuman("No successful publish confirmation appeared.")


def _dismiss_tiktok_tour(page: Any) -> None:
    """Dismiss TikTok Studio's first-run Joyride tour through its own UI."""
    for _ in range(8):
        overlay = page.locator("[data-test-id='overlay']")
        if not _visible(overlay):
            return
        got_it = _visible_match(page.get_by_role("button", name="Got it", exact=True))
        if got_it is None:
            raise PublishNeedsHuman(
                "TikTok's onboarding overlay is blocking the Post button."
            )
        got_it.click()
        page.wait_for_timeout(400)
    if _visible(page.locator("[data-test-id='overlay']")):
        raise PublishNeedsHuman("TikTok's onboarding tour could not be dismissed.")


def _publish_instagram(
    controller: BrowserController, media_path: Path, caption: str
) -> None:
    page = controller.page
    controller.goto(PLATFORM_URLS["instagram"], timeout_ms=60000)
    page.wait_for_timeout(2500)
    _check_blocking_screen(controller, "instagram")

    create = page.locator("a:has(svg[aria-label='New post'])")
    if not _visible(create):
        raise PublishNeedsHuman("Instagram's New post (+) control was not found.")
    create.first.click()

    upload = page.locator("[role='dialog'] input[type='file']")
    if upload.count() == 0:
        upload = page.locator("input[type='file']")
    if upload.count() == 0:
        raise PublishNeedsHuman("Instagram's hidden video upload input was not found.")
    upload.first.set_input_files(str(media_path))
    page.wait_for_timeout(1500)

    # Instagram shows this once per account/browser profile.
    _click_if_visible(page.get_by_role("button", name="OK", exact=True))

    crop_icon = _visible_match(
        page.locator("[role='dialog'] svg[aria-label='Select Crop']")
    )
    if crop_icon is None:
        raise PublishNeedsHuman("Instagram's crop control was not found.")
    crop_icon.click()
    vertical = _first_visible(
        page,
        ["[role='dialog'] [role='button']:has-text('9:16')"],
        timeout_s=10,
    )
    if vertical.inner_text().strip() != "9:16":
        raise PublishNeedsHuman("Instagram's exact 9:16 crop option was not found.")
    vertical.click()

    for _ in range(2):
        next_button = _first_visible(
            page,
            [
                "[role='dialog'] [role='button']:has-text('Next')",
                "[role='dialog'] button:has-text('Next')",
            ],
            timeout_s=30,
        )
        next_button.click()
        page.wait_for_timeout(1000)

    caption_box = page.locator(
        "[role='dialog'] [role='textbox'][aria-label='Write a caption...']"
    )
    if not _visible(caption_box):
        raise PublishNeedsHuman("Instagram's caption field was not found.")
    caption_box.fill(caption)
    share = _first_visible(
        page,
        [
            "[role='dialog'] [role='button']:has-text('Share')",
            "[role='dialog'] button:has-text('Share')",
        ],
        timeout_s=20,
    )
    share.click()
    _wait_for_publish_result(
        page,
        [
            r"your reel has been shared",
            r"your post has been shared",
            r"reel shared",
            r"post shared",
        ],
    )


def _publish_tiktok(
    controller: BrowserController, media_path: Path, caption: str
) -> None:
    page = controller.page
    controller.goto(PLATFORM_URLS["tiktok"], timeout_ms=60000)
    page.wait_for_timeout(2500)
    _check_blocking_screen(controller, "tiktok")
    _set_files(page, media_path)

    uploaded = page.locator(
        "[data-e2e='upload_status_container']:has-text('Uploaded')"
    )
    _first_visible(
        page,
        ["[data-e2e='upload_status_container']:has-text('Uploaded')"],
        timeout_s=60,
    )
    if not _visible(uploaded):
        raise PublishNeedsHuman("TikTok did not confirm that the video uploaded.")

    caption_box = page.locator(
        "[data-e2e='caption_container'] [contenteditable='true'][role='combobox']"
    )
    if not _visible(caption_box):
        raise PublishNeedsHuman("TikTok's description field was not found.")
    caption_box.fill(caption)

    # The generated videos in this pipeline are AI-generated, so preserve the
    # platform's disclosure instead of silently posting them as ordinary video.
    ai_switch = page.locator(
        "[data-e2e='aigc_container'] input[role='switch'], "
        "[data-e2e='aigc_container'] input[type='checkbox']"
    )
    if _visible(ai_switch) and not ai_switch.first.is_checked():
        ai_switch.first.check()

    _dismiss_tiktok_tour(page)
    post = _wait_for_enabled(
        page.locator("button[data-e2e='post_video_button']"),
        timeout_s=60,
    )
    post.click()

    # TikTok may ask whether to post before its asynchronous content check has
    # completed. This is a normal confirmation dialog, not a safety refusal.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        post_now = _visible_match(
            page.get_by_role("button", name="Post now", exact=True)
        )
        if post_now is not None:
            post_now.click()
            break
        if "/tiktokstudio/upload" not in page.url:
            break
        time.sleep(0.25)

    _wait_for_publish_result(
        page,
        [
            r"uploaded successfully",
            r"posted successfully",
            r"published successfully",
            r"your video is being uploaded",
            r"your video has been posted",
        ],
        success_url_excludes="/tiktokstudio/upload",
    )


def publish_job(
    job: Job,
    store: JobStore,
    platforms: list[str] | None = None,
    *,
    controllers: dict[str, BrowserController] | None = None,
) -> Job:
    """Publish a rendered job and persist a per-platform audit result."""
    if not config.publishing_enabled():
        raise RuntimeError(
            "Publishing is disabled. Set social_video_factory.publishing.enabled "
            "to true in ~/.hermes/config.yaml."
        )
    source = Path(job.rendered_path or "")
    if not source.is_file():
        raise RuntimeError("job has no finished rendered video to publish")
    selected = [_platform(p) for p in (platforms or config.publish_platforms())]
    job.advance(JobStatus.APPROVED, note="publishing explicitly enabled in config")
    job.advance(JobStatus.PUBLISHING, note=f"publishing to {', '.join(selected)}")
    store.save(job)

    for platform in selected:
        browser = (controllers or {}).get(platform) or controller_for(platform)
        try:
            browser.start()
            if platform == "instagram":
                _publish_instagram(browser, source, str(job.captions.get(platform, "")))
            else:
                _publish_tiktok(browser, source, str(job.captions.get(platform, "")))
            job.publish_results[platform] = {"status": "published"}
        except PublishNeedsHuman as exc:
            browser.screenshot(config.logs_dir() / f"{job.id}_{platform}_blocked.png")
            job.publish_results[platform] = {
                "status": "needs_human",
                "reason": str(exc),
            }
        except Exception as exc:
            browser.screenshot(config.logs_dir() / f"{job.id}_{platform}_error.png")
            job.publish_results[platform] = {"status": "error", "reason": str(exc)}
        finally:
            browser.close()
            store.save(job)

    published = sum(
        job.publish_results.get(platform, {}).get("status") == "published"
        for platform in selected
    )
    if published == len(selected):
        job.advance(JobStatus.PUBLISHED, note=f"published to {', '.join(selected)}")
    elif published:
        job.advance(JobStatus.PUBLISH_PARTIAL, note="some platforms need attention")
    else:
        job.needs_human_reason = "social publishing needs human attention"
        job.advance(JobStatus.NEEDS_HUMAN, note=job.needs_human_reason)
    store.save(job)
    return job


def maybe_auto_publish(job: Job, store: JobStore) -> Job:
    """Continue into publishing only when the user explicitly opted in."""
    if config.auto_publish():
        return publish_job(job, store)
    return job
