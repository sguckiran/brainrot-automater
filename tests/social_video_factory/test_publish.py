"""Browser publishing orchestration without real websites or accounts."""

from __future__ import annotations

from social_video_factory import publish
from social_video_factory.models import Job, JobStatus
from social_video_factory.store import JobStore


class FakeController:
    def __init__(self) -> None:
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def close(self) -> None:
        self.closed = True

    def screenshot(self, _path):
        return None


def _configured(monkeypatch, tmp_path) -> None:
    hermes_home = tmp_path / "hermes"
    hermes_home.mkdir()
    (hermes_home / "config.yaml").write_text(
        "social_video_factory:\n"
        "  publishing:\n"
        "    enabled: true\n"
        "    auto_after_generation: true\n"
        "    platforms: [instagram, tiktok]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("SOCIAL_FACTORY_DATA_DIR", str(tmp_path / "data"))


def _job(tmp_path) -> Job:
    video = tmp_path / "finished.mp4"
    video.write_bytes(b"video")
    return Job(
        topic="test",
        rendered_path=str(video),
        captions={"instagram": "ig caption #tag", "tiktok": "tt caption #tag"},
        status=JobStatus.AWAITING_APPROVAL.value,
    )


def test_publish_job_records_both_platforms(monkeypatch, tmp_path):
    _configured(monkeypatch, tmp_path)
    job = _job(tmp_path)
    store = JobStore()
    store.save(job)
    instagram = FakeController()
    tiktok = FakeController()
    calls = []

    monkeypatch.setattr(
        publish,
        "_publish_instagram",
        lambda _controller, _path, caption: calls.append(("instagram", caption)),
    )
    monkeypatch.setattr(
        publish,
        "_publish_tiktok",
        lambda _controller, _path, caption: calls.append(("tiktok", caption)),
    )

    publish.publish_job(
        job,
        store,
        controllers={"instagram": instagram, "tiktok": tiktok},
    )

    assert job.status == JobStatus.PUBLISHED.value
    assert job.publish_results == {
        "instagram": {"status": "published"},
        "tiktok": {"status": "published"},
    }
    assert calls == [
        ("instagram", "ig caption #tag"),
        ("tiktok", "tt caption #tag"),
    ]
    assert instagram.started and instagram.closed
    assert tiktok.started and tiktok.closed


def test_publish_job_stops_cleanly_for_human_attention(monkeypatch, tmp_path):
    _configured(monkeypatch, tmp_path)
    job = _job(tmp_path)
    store = JobStore()
    store.save(job)

    def _blocked(*_args):
        raise publish.PublishNeedsHuman("verification required")

    monkeypatch.setattr(publish, "_publish_instagram", _blocked)
    monkeypatch.setattr(publish, "_publish_tiktok", _blocked)
    publish.publish_job(
        job,
        store,
        controllers={
            "instagram": FakeController(),
            "tiktok": FakeController(),
        },
    )

    assert job.status == JobStatus.NEEDS_HUMAN.value
    assert all(
        result["status"] == "needs_human"
        for result in job.publish_results.values()
    )


def test_publish_job_requires_explicit_enable(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "missing"))
    monkeypatch.setenv("SOCIAL_FACTORY_DATA_DIR", str(tmp_path / "data"))
    job = _job(tmp_path)
    store = JobStore()
    store.save(job)

    try:
        publish.publish_job(job, store)
    except RuntimeError as exc:
        assert "Publishing is disabled" in str(exc)
    else:
        raise AssertionError("publishing must require explicit opt-in")


def test_publish_job_skips_already_published_platform(monkeypatch, tmp_path):
    _configured(monkeypatch, tmp_path)
    job = _job(tmp_path)
    job.publish_results = {"instagram": {"status": "published"}}
    store = JobStore()
    store.save(job)
    calls = []

    monkeypatch.setattr(
        publish,
        "_publish_instagram",
        lambda *_args: calls.append("instagram"),
    )
    monkeypatch.setattr(
        publish,
        "_publish_tiktok",
        lambda *_args: calls.append("tiktok"),
    )

    publish.publish_job(
        job,
        store,
        controllers={"tiktok": FakeController()},
    )

    assert calls == ["tiktok"]
    assert job.status == JobStatus.PUBLISHED.value


def test_publish_job_does_not_retry_interrupted_platform(monkeypatch, tmp_path):
    _configured(monkeypatch, tmp_path)
    job = _job(tmp_path)
    job.publish_results = {"instagram": {"status": "publishing"}}
    store = JobStore()
    store.save(job)

    monkeypatch.setattr(
        publish,
        "_publish_instagram",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("interrupted platform must not be retried")
        ),
    )

    publish.publish_job(job, store, platforms=["instagram"])

    assert job.status == JobStatus.NEEDS_HUMAN.value
    assert job.publish_results["instagram"]["status"] == "needs_human"
    assert "unknown external result" in job.publish_results["instagram"]["reason"]


def test_publish_job_does_not_retry_legacy_interrupted_job(monkeypatch, tmp_path):
    _configured(monkeypatch, tmp_path)
    job = _job(tmp_path)
    job.status = JobStatus.PUBLISHING.value
    store = JobStore()
    store.save(job)

    publish.publish_job(job, store, platforms=["instagram", "tiktok"])

    assert job.status == JobStatus.NEEDS_HUMAN.value
    assert set(job.publish_results) == {"instagram", "tiktok"}
    assert all(
        result["status"] == "needs_human"
        for result in job.publish_results.values()
    )


def test_dismiss_tiktok_tour_clicks_got_it_until_overlay_is_gone():
    class Locator:
        def __init__(self, page, kind):
            self.page = page
            self.kind = kind

        @property
        def first(self):
            return self

        def nth(self, _index):
            return self

        def count(self):
            return int(self.page.steps > 0)

        def is_visible(self):
            return self.page.steps > 0

        def click(self):
            self.page.steps -= 1

    class Page:
        def __init__(self):
            self.steps = 2

        def locator(self, _selector):
            return Locator(self, "overlay")

        def get_by_role(self, _role, **_kwargs):
            return Locator(self, "button")

        def wait_for_timeout(self, _milliseconds):
            return None

    page = Page()
    publish._dismiss_tiktok_tour(page)
    assert page.steps == 0


def test_instagram_upload_uses_lazy_file_chooser(tmp_path):
    media = tmp_path / "video.mp4"
    media.write_bytes(b"video")
    selected: list[str] = []

    class MissingInput:
        def count(self):
            return 0

    class Button:
        def is_visible(self):
            return True

        def click(self):
            selected.append("clicked")

    class Buttons:
        @property
        def first(self):
            return Button()

        def count(self):
            return 1

        def nth(self, _index):
            return Button()

    class Chooser:
        def set_files(self, path):
            selected.append(path)

    class ChooserInfo:
        value = Chooser()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    class Page:
        def locator(self, _selector):
            return MissingInput()

        def get_by_role(self, _role, **_kwargs):
            return Buttons()

        def expect_file_chooser(self, timeout):
            assert timeout == 20000
            return ChooserInfo()

    publish._set_instagram_media(Page(), media)

    assert selected == ["clicked", str(media)]
