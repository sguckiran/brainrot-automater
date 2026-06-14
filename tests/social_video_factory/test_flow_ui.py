"""Google Flow's current project/composer/detail-page UI contract."""

from __future__ import annotations

from pathlib import Path

from social_video_factory.browser import flow_ui


class FakeElement:
    def __init__(self, text="", *, attrs=None, on_click=None, ancestor=None):
        self.text = text
        self.attrs = dict(attrs or {})
        self.on_click = on_click
        self.ancestor = ancestor
        self.filled = None

    def inner_text(self):
        return self.text

    def get_attribute(self, name):
        return self.attrs.get(name)

    def click(self):
        if self.on_click:
            self.on_click()

    def fill(self, text):
        self.filled = text

    def is_visible(self):
        return True

    def is_disabled(self):
        return False

    def locator(self, selector):
        assert selector == "xpath=ancestor::a[1]"
        return self.ancestor


class FakeList:
    def __init__(self, items):
        self.items = items

    def count(self):
        return len(self.items)

    def nth(self, index):
        return self.items[index]

    @property
    def first(self):
        return self.items[0]


class FakePage:
    def __init__(self):
        self.url = "https://labs.google/fx/tools/flow"
        self.state = "list"
        self.project_links = ["/fx/tools/flow/project/old"]
        self.settings_open = False
        self.prompt = FakeElement()
        self.video_items = []

    def _set_active(self, target):
        for button in self._settings_buttons():
            button.attrs["data-state"] = "inactive"
        target.attrs["data-state"] = "active"

    def _settings_buttons(self):
        video = FakeElement(
            "play_circle\nVideo",
            attrs={"data-state": "inactive"},
        )
        portrait = FakeElement(
            "crop_9_16\n9:16",
            attrs={"data-state": "inactive"},
        )
        one = FakeElement("1x", attrs={"data-state": "inactive"})
        for button in (video, portrait, one):
            button.on_click = lambda item=button: self._set_active(item)
        return [video, portrait, one]

    def _buttons(self):
        if self.state == "list":
            def create():
                self.project_links.insert(0, "/fx/tools/flow/project/new")

            return [
                FakeElement("No thanks"),
                FakeElement("add_2\nNew project", on_click=create),
            ]

        summary = FakeElement(
            "Nano Banana 2\ncrop_16_9\nx2",
            attrs={"data-state": "open" if self.settings_open else "closed"},
            on_click=lambda: setattr(self, "settings_open", not self.settings_open),
        )
        buttons = [summary, FakeElement("arrow_forward\nCreate")]
        if self.settings_open:
            buttons.extend(self._settings_buttons())
        return buttons

    def locator(self, selector):
        if selector == "button":
            return FakeList(self._buttons())
        if selector == "a[href*='/fx/tools/flow/project/']":
            return FakeList(
                [FakeElement(attrs={"href": href}) for href in self.project_links]
            )
        if selector == "div[contenteditable='true'][role='textbox']":
            return FakeList([self.prompt] if self.state == "project" else [])
        if selector == "a[href*='/edit/']":
            return FakeList(
                [video.ancestor for video in self.video_items if video.ancestor]
            )
        if selector == "video":
            return FakeList(self.video_items)
        raise AssertionError(selector)

    def goto(self, url, **_kwargs):
        self.url = url
        self.state = "detail" if "/edit/" in url else "project"


class FakeController:
    def __init__(self, page, output):
        self.page = page
        self.output = output
        self.goto_url = None

    def goto(self, url):
        self.goto_url = url
        self.page.goto(url)

    def expect_download(self, trigger):
        trigger()
        return self.output


def test_prepare_generation_creates_project_and_configures_portrait(monkeypatch):
    page = FakePage()
    monkeypatch.setattr(flow_ui.time, "sleep", lambda _seconds: None)

    prepared = flow_ui.prepare_generation(
        page,
        "https://labs.google/fx/tools/flow",
        "orange cat prompt",
        timeout_s=1,
    )

    assert page.url.endswith("/fx/tools/flow/project/new")
    assert prepared.prompt_box.filled == "orange cat prompt"
    assert prepared.baseline_edit_urls == frozenset()
    assert prepared.submit.inner_text() == "arrow_forward\nCreate"


def test_prepare_generation_accepts_direct_editor_navigation(monkeypatch):
    page = FakePage()
    original_buttons = page._buttons

    def direct_buttons():
        if page.state == "list":
            def open_editor():
                page.state = "project"
                page.url = "https://labs.google/fx/tools/flow/project/direct"

            return [FakeElement("add_2\nNew project", on_click=open_editor)]
        return original_buttons()

    monkeypatch.setattr(page, "_buttons", direct_buttons)
    monkeypatch.setattr(flow_ui.time, "sleep", lambda _seconds: None)

    prepared = flow_ui.prepare_generation(
        page,
        "https://labs.google/fx/tools/flow",
        "direct editor prompt",
        timeout_s=1,
    )

    assert page.url.endswith("/project/direct")
    assert prepared.prompt_box.filled == "direct editor prompt"


def test_new_result_url_comes_from_video_card():
    page = FakePage()
    page.state = "project"
    page.url = "https://labs.google/fx/tools/flow/project/new"
    link = FakeElement(attrs={"href": "/fx/tools/flow/project/new/edit/result"})
    page.video_items = [FakeElement(ancestor=link)]

    assert flow_ui.new_result_edit_url(page, frozenset()).endswith("/edit/result")
    assert (
        flow_ui.new_result_edit_url(
            page,
            {
                "https://labs.google/fx/tools/flow/project/new/edit/result",
            },
        )
        is None
    )


def test_download_from_detail_uses_detail_download_button(tmp_path, monkeypatch):
    page = FakePage()
    page.state = "detail"
    output = tmp_path / "clip.mp4"
    output.write_bytes(b"video")

    original_buttons = page._buttons

    def detail_buttons():
        if page.state == "detail":
            return [FakeElement("download\nDownload")]
        return original_buttons()

    monkeypatch.setattr(page, "_buttons", detail_buttons)
    monkeypatch.setattr(flow_ui.time, "sleep", lambda _seconds: None)
    controller = FakeController(page, output)

    downloaded = flow_ui.download_from_detail(
        controller,
        "https://labs.google/fx/tools/flow/project/new/edit/result",
        timeout_s=1,
    )

    assert downloaded == Path(output)
    assert controller.goto_url.endswith("/edit/result")
