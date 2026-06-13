"""Browser worker flow against FAKES — no real browser / Playwright / network.

Covers the four behaviours the brief requires:
  * happy path -> success, job reaches awaiting_approval, record() called once;
  * hard-stop page -> needs_human, reason set, browser closed, NO record();
  * rate-limited -> rate_limited, browser NEVER started;
  * selector miss on prompt_box -> manual_pause invoked, then proceeds.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from social_video_factory import config
from social_video_factory.browser import worker as worker_mod
from social_video_factory.browser.worker import generate_in_browser
from social_video_factory.models import GenerationMode, Job, JobStatus
from social_video_factory.store import JobStore


@pytest.fixture(autouse=True)
def _tmp_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SOCIAL_FACTORY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SOCIAL_FACTORY_FLOW_URL", "https://example.test/flow")
    # Make the worker poll fast and not sleep.
    monkeypatch.setattr(worker_mod.time, "sleep", lambda _s: None)
    return tmp_path


# --- fakes ----------------------------------------------------------------


class FakeLocator:
    """A located UI control. Records fill/click; can hold a value."""

    def __init__(self, value=""):
        self.value = value
        self.clicked = False
        self.filled = None

    def fill(self, text):
        self.filled = text
        self.value = text

    def click(self):
        self.clicked = True

    def input_value(self):
        return self.value


class FakeController:
    """Duck-typed BrowserController. Drives html + a fake download."""

    def __init__(self, html="ready", download_name="clip.mp4", make_real_file=True):
        self._html = html
        self.started = False
        self.closed = False
        self.goto_url = None
        self._download_name = download_name
        self._make_real = make_real_file
        self.page = object()  # opaque; SelectorResolver is patched in tests

    def start(self):
        self.started = True

    def goto(self, url, **kwargs):
        self.goto_url = url

    def html(self):
        return self._html

    def screenshot(self, path):
        return None

    def expect_download(self, trigger, timeout_ms=120000):
        trigger()
        target = config.downloads_dir() / self._download_name
        if self._make_real:
            target.write_bytes(b"\x00\x00\x00\x18ftypisom")
        return target

    def wait_for_enter(self, message):
        pass

    def close(self):
        self.closed = True


class FakeResolver:
    """Stands in for SelectorResolver. Returns canned locators per action."""

    def __init__(self, locators=None, missing=(), manual_log=None):
        self._locators = locators or {}
        self._missing = set(missing)
        self.manual_log = manual_log if manual_log is not None else []

    def locate(self, action_key):
        if action_key in self._missing:
            return None
        return self._locators.get(action_key)

    def manual_pause(self, reason):
        self.manual_log.append(reason)
        return None


class FakeRateLimiter:
    """Injected limiter. allowed/needs_confirm configurable; records calls."""

    def __init__(self, allowed=True, reason=None, needs_human_confirm=False,
                 confirm_result=True):
        from social_video_factory.rate_limit import RateDecision

        self._decision = RateDecision(
            allowed=allowed, reason=reason, needs_human_confirm=needs_human_confirm
        )
        self.confirm = lambda _m: confirm_result
        self.records = 0

    def check(self):
        return self._decision

    def record(self):
        self.records += 1


def _make_job():
    job = Job(
        template="dancing_cat",
        topic="orange cat disco",
        generation_mode=GenerationMode.BROWSER_FLOW.value,
        target="flow",
        prompt="a dancing cat in a disco kitchen",
    )
    return job


def _full_locators():
    return {
        "prompt_box": FakeLocator(),
        "submit": FakeLocator(),
        "download": FakeLocator(),
        "export_mp4": FakeLocator(),
        # result_video present so the wait loop completes immediately.
        "result_video": FakeLocator(),
    }


# --- tests ----------------------------------------------------------------


def test_happy_path_reaches_awaiting_approval(monkeypatch):
    store = JobStore()
    job = _make_job()
    store.save(job)

    controller = FakeController()
    rl = FakeRateLimiter()
    resolver = FakeResolver(locators=_full_locators())
    monkeypatch.setattr(worker_mod, "SelectorResolver", lambda *a, **k: resolver)

    outcome = generate_in_browser(
        job, store, controller=controller, rate_limiter=rl,
        selectors_config={}, poll_timeout_s=5, poll_interval_s=0,
    )

    assert outcome.status == "success"
    assert outcome.downloaded_path is not None
    assert rl.records == 1
    assert controller.started is True
    assert controller.closed is True
    reloaded = JobStore().load(job.id)
    assert reloaded.status == JobStatus.AWAITING_APPROVAL.value
    # The prompt was actually pasted into the box.
    assert resolver._locators["prompt_box"].filled == job.prompt


def test_hard_stop_marks_needs_human_no_record(monkeypatch):
    store = JobStore()
    job = _make_job()
    store.save(job)

    controller = FakeController(html="Please sign in to continue")
    rl = FakeRateLimiter()
    resolver = FakeResolver(locators=_full_locators())
    monkeypatch.setattr(worker_mod, "SelectorResolver", lambda *a, **k: resolver)

    outcome = generate_in_browser(
        job, store, controller=controller, rate_limiter=rl, selectors_config={},
    )

    assert outcome.status == "needs_human"
    assert "login" in (outcome.reason or "")
    assert rl.records == 0  # never recorded a generation
    assert controller.closed is True
    reloaded = JobStore().load(job.id)
    assert reloaded.status == JobStatus.NEEDS_HUMAN.value
    assert reloaded.needs_human_reason


def test_rate_limited_never_starts_browser(monkeypatch):
    store = JobStore()
    job = _make_job()
    store.save(job)

    controller = FakeController()
    rl = FakeRateLimiter(allowed=False, reason="hourly cap reached (3/3)")

    outcome = generate_in_browser(
        job, store, controller=controller, rate_limiter=rl, selectors_config={},
    )

    assert outcome.status == "rate_limited"
    assert controller.started is False  # browser NEVER opened
    assert rl.records == 0


def test_human_confirm_declined_returns_needs_human(monkeypatch):
    store = JobStore()
    job = _make_job()
    store.save(job)

    controller = FakeController()
    rl = FakeRateLimiter(needs_human_confirm=True, confirm_result=False)

    outcome = generate_in_browser(
        job, store, controller=controller, rate_limiter=rl, selectors_config={},
    )

    assert outcome.status == "needs_human"
    assert "confirm declined" in (outcome.reason or "")
    assert controller.started is False
    # Consistency: the declined path persists NEEDS_HUMAN + a reason on the job.
    reloaded = JobStore().load(job.id)
    assert reloaded.status == JobStatus.NEEDS_HUMAN.value
    assert reloaded.needs_human_reason == "human confirm declined"


def test_prompt_box_miss_falls_back_to_manual_pause(monkeypatch):
    store = JobStore()
    job = _make_job()
    store.save(job)

    controller = FakeController()
    rl = FakeRateLimiter()
    manual_log: list[str] = []
    locators = _full_locators()
    resolver = FakeResolver(
        locators=locators, missing=("prompt_box",), manual_log=manual_log
    )
    monkeypatch.setattr(worker_mod, "SelectorResolver", lambda *a, **k: resolver)

    outcome = generate_in_browser(
        job, store, controller=controller, rate_limiter=rl,
        selectors_config={}, poll_timeout_s=5, poll_interval_s=0,
    )

    # manual_pause fired for the missing prompt box, then the flow proceeded.
    assert any("paste this prompt" in m for m in manual_log)
    assert outcome.status == "success"
    assert rl.records == 1


def test_no_url_configured_returns_error(monkeypatch):
    monkeypatch.setenv("SOCIAL_FACTORY_FLOW_URL", "")
    store = JobStore()
    job = _make_job()
    store.save(job)
    controller = FakeController()
    rl = FakeRateLimiter()

    outcome = generate_in_browser(
        job, store, controller=controller, rate_limiter=rl, selectors_config={},
    )
    assert outcome.status == "error"
    assert controller.started is False


def test_no_video_download_marks_needs_human(monkeypatch):
    store = JobStore()
    job = _make_job()
    store.save(job)
    # Controller returns a non-video file name and we ensure downloads dir empty.
    controller = FakeController(download_name="result.txt")
    rl = FakeRateLimiter()
    resolver = FakeResolver(locators=_full_locators())
    monkeypatch.setattr(worker_mod, "SelectorResolver", lambda *a, **k: resolver)

    outcome = generate_in_browser(
        job, store, controller=controller, rate_limiter=rl,
        selectors_config={}, poll_timeout_s=5, poll_interval_s=0,
    )
    assert outcome.status == "needs_human"
    assert "no video download" in (outcome.reason or "")
    assert rl.records == 0
