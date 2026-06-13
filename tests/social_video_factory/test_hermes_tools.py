"""Phase 5 — Hermes tool surface for social_video_factory.

No real browser / Playwright / network.  Covers:
  * all four tools register + check_fn True;
  * browser_login returns JSON guidance (CLI command + profile_exists) and
    NEVER opens a browser, even with no URL configured;
  * browser_generate_job with a missing job_id -> JSON error (no exception);
  * import_latest_browser_download with an empty downloads dir -> JSON error;
  * _NonBlockingController.wait_for_enter returns immediately WITHOUT reading
    stdin (input() is monkeypatched to raise — it must not be called);
  * browser_generate_job injects a NON-interactive rate limiter (confirm()
    is False) and a non-blocking controller; happy-path via injected fakes
    reaches status="success".
"""

from __future__ import annotations

import builtins
import json

import pytest

import tools.social_video_factory_tool as svf_tool
from social_video_factory.models import GenerationMode, Job, JobStatus
from social_video_factory.store import JobStore
from tools.registry import registry

_TOOL_NAMES = [
    "social_video_factory_browser_login",
    "social_video_factory_browser_generate_job",
    "social_video_factory_browser_run_queue",
    "social_video_factory_import_latest_browser_download",
]


@pytest.fixture(autouse=True)
def _tmp_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SOCIAL_FACTORY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("SOCIAL_FACTORY_BROWSER_DOWNLOAD_DIR", raising=False)
    # Ensure a clean, isolated profile dir under the tmp data root.
    monkeypatch.delenv("SOCIAL_FACTORY_BROWSER_PROFILE_DIR", raising=False)
    monkeypatch.delenv("SOCIAL_FACTORY_FLOW_URL", raising=False)
    monkeypatch.delenv("SOCIAL_FACTORY_GEMINI_URL", raising=False)
    return tmp_path


# --- registration ----------------------------------------------------------


def test_all_four_tools_register_and_check_true():
    for name in _TOOL_NAMES:
        entry = registry.get_entry(name)
        assert entry is not None, f"{name} not registered"
        assert entry.toolset == "social_video_factory"
        assert entry.check_fn is svf_tool._svf_available
    assert svf_tool._svf_available() is True


def test_generate_tool_advertises_plain_video_requests_as_vertical():
    description = svf_tool._GENERATE_SCHEMA["description"]
    assert "whenever the user asks" in description
    assert "vertical 9:16" in description


def test_tools_appear_under_toolset():
    names = registry.get_tool_names_for_toolset("social_video_factory")
    assert set(_TOOL_NAMES).issubset(set(names))


# --- browser_login (guidance only) -----------------------------------------


def test_browser_login_returns_guidance_with_no_url(monkeypatch):
    # Guard: if anything tries to open a browser, fail loudly.
    def _boom():  # pragma: no cover - must never be called
        raise AssertionError("browser_login must not open a browser")

    monkeypatch.setattr(svf_tool, "_wrapped_controller", _boom)

    out = svf_tool._handle_browser_login({"target": "flow"})
    data = json.loads(out)

    assert "browser-login --target flow" in data["command"]
    assert isinstance(data["profile_exists"], bool)
    # No URL configured -> guidance still returned, no exception, with a note.
    assert data["resolved_url"] is None
    assert data["url_note"]


def test_browser_login_uses_configured_url(monkeypatch):
    monkeypatch.setenv("SOCIAL_FACTORY_GEMINI_URL", "https://example.test/gemini")
    out = svf_tool._handle_browser_login({"target": "gemini"})
    data = json.loads(out)
    assert data["resolved_url"] == "https://example.test/gemini"
    assert data["url_note"] is None
    assert "--target gemini" in data["command"]


# --- error paths ------------------------------------------------------------


def test_generate_job_missing_id_returns_json_error():
    out = svf_tool._handle_browser_generate_job({"job_id": "does-not-exist"})
    data = json.loads(out)
    assert "error" in data
    assert "not found" in data["error"]


def test_generate_job_requires_id_or_topic():
    out = svf_tool._handle_browser_generate_job({})
    data = json.loads(out)
    assert "provide job_id or topic" in data["error"]


def test_import_latest_empty_downloads_returns_json_error():
    store = JobStore()
    job = Job(
        template="dancing_cat",
        topic="orange cat disco",
        generation_mode=GenerationMode.BROWSER_FLOW.value,
        target="flow",
        prompt="a dancing cat",
        status=JobStatus.PROMPTED.value,
    )
    store.save(job)

    out = svf_tool._handle_import_latest({"job_id": job.id})
    data = json.loads(out)
    assert "error" in data
    assert "no video download" in data["error"]


def test_import_latest_missing_job_returns_json_error():
    out = svf_tool._handle_import_latest({"job_id": "nope"})
    data = json.loads(out)
    assert "error" in data


# --- NON-BLOCKING controller ------------------------------------------------


class _FakeInner:
    """Records delegated calls; exposes a `page` attribute."""

    def __init__(self):
        self.page = object()
        self.closed = False
        self.waited = None

    def close(self):
        self.closed = True

    def html(self):
        return "ready"


def test_non_blocking_controller_does_not_read_stdin(monkeypatch):
    def _no_input(*_a, **_k):  # pragma: no cover - must never be called
        raise AssertionError("wait_for_enter must not read stdin")

    monkeypatch.setattr(builtins, "input", _no_input)

    inner = _FakeInner()
    wrapped = svf_tool._NonBlockingController(inner)

    # The override returns immediately without touching stdin.
    assert wrapped.wait_for_enter("please do a manual step") is None

    # Everything else delegates to the inner controller.
    assert wrapped.page is inner.page
    assert wrapped.html() == "ready"
    wrapped.close()
    assert inner.closed is True


def test_non_interactive_rate_limiter_confirm_is_false():
    rl = svf_tool._non_interactive_rate_limiter()
    assert rl.confirm("proceed?") is False


# --- happy path via injected fakes -----------------------------------------


def test_generate_job_happy_path_success(monkeypatch):
    """The tool injects a non-interactive limiter + non-blocking controller and
    reaches status='success'. We capture the kwargs the worker received and
    assert their non-interactive shape, then return a fake success outcome."""
    store = JobStore()
    job = Job(
        template="dancing_cat",
        topic="orange cat disco",
        generation_mode=GenerationMode.BROWSER_FLOW.value,
        target="flow",
        prompt="a dancing cat in a disco kitchen",
        status=JobStatus.PROMPTED.value,
    )
    store.save(job)

    captured = {}

    from social_video_factory.browser.worker import GenerationOutcome

    def _fake_generate(j, s, *, controller, rate_limiter, **_kw):
        captured["controller"] = controller
        captured["rate_limiter"] = rate_limiter
        # Advance the job so the tool's reload reflects a finished run.
        j.advance(JobStatus.AWAITING_APPROVAL, note="fake success")
        s.save(j)
        return GenerationOutcome(
            status="success", job_id=j.id, downloaded_path="/tmp/clip.mp4"
        )

    # Patch the symbol the handler imports lazily.
    import social_video_factory.browser.worker as worker_mod

    monkeypatch.setattr(worker_mod, "generate_in_browser", _fake_generate)

    out = svf_tool._handle_browser_generate_job({"job_id": job.id})
    data = json.loads(out)

    assert data["status"] == "success"
    assert data["job_id"] == job.id
    assert data["job_status"] == JobStatus.AWAITING_APPROVAL.value

    # Non-interactive shape: confirm() declines (no stdin) and the controller's
    # wait_for_enter is the non-blocking no-op.
    assert captured["rate_limiter"].confirm("proceed?") is False
    assert isinstance(captured["controller"], svf_tool._NonBlockingController)
    assert captured["controller"].wait_for_enter("x") is None


def test_generate_job_can_create_from_topic(monkeypatch):
    captured = {}

    from social_video_factory.browser.worker import GenerationOutcome

    def _fake_generate(job, store, **_kwargs):
        captured["job"] = job
        job.advance(JobStatus.AWAITING_APPROVAL, note="fake success")
        store.save(job)
        return GenerationOutcome(status="success", job_id=job.id)

    import social_video_factory.browser.worker as worker_mod

    monkeypatch.setattr(worker_mod, "generate_in_browser", _fake_generate)

    out = svf_tool._handle_browser_generate_job(
        {
            "topic": "orange cat disco kitchen",
            "template": "dancing_cat",
            "target": "flow",
        }
    )
    data = json.loads(out)

    assert data["status"] == "success"
    assert captured["job"].topic == "orange cat disco kitchen"
    assert captured["job"].generation_mode == GenerationMode.BROWSER_FLOW.value
    assert captured["job"].prompt
