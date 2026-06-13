"""Config defaults + env overrides, all under a tmp data dir."""

from __future__ import annotations

from pathlib import Path

from social_video_factory import config


def test_data_dir_uses_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path / "data"))
    root = config.data_dir()
    assert root == tmp_path / "data"
    assert root.is_dir()


def test_data_dir_defaults_to_cwd(monkeypatch, tmp_path):
    monkeypatch.delenv(config.ENV_DATA_DIR, raising=False)
    monkeypatch.chdir(tmp_path)
    root = config.data_dir()
    assert root == tmp_path / config.DEFAULT_DATA_DIR_NAME
    assert root.is_dir()


def test_path_helpers_create_dirs_lazily(monkeypatch, tmp_path):
    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))
    for helper in (
        config.jobs_dir,
        config.imported_dir,
        config.rendered_dir,
        config.state_dir,
        config.logs_dir,
        config.profile_dir,
        config.downloads_dir,
    ):
        path = helper()
        assert path.is_dir(), helper.__name__


def test_browser_download_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))
    custom = tmp_path / "elsewhere" / "dl"
    monkeypatch.setenv(config.ENV_BROWSER_DOWNLOAD_DIR, str(custom))
    assert config.downloads_dir() == custom
    assert custom.is_dir()


def test_typed_config_accessors_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))
    for name in (
        config.ENV_MAX_GEN_PER_HOUR,
        config.ENV_MAX_GEN_PER_DAY,
        config.ENV_MIN_SECONDS_BETWEEN_GEN,
        config.ENV_REQUIRE_HUMAN_CONFIRM_EVERY,
        config.ENV_BROWSER_HEADLESS,
        config.ENV_AUTO_PUBLISH,
        config.ENV_FLOW_URL,
        config.ENV_GEMINI_URL,
        config.ENV_BROWSER_EXECUTABLE_PATH,
    ):
        monkeypatch.delenv(name, raising=False)
    assert config.max_generations_per_hour() == 3
    assert config.max_generations_per_day() == 20
    assert config.min_seconds_between_generations() == 180
    assert config.require_human_confirm_every() == 10
    assert config.browser_headless() is False
    assert config.auto_publish() is False
    assert config.browser_executable_path() is None
    assert config.flow_url() == ""
    assert config.gemini_url() == ""


def test_bool_and_int_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))
    monkeypatch.setenv(config.ENV_BROWSER_HEADLESS, "true")
    monkeypatch.setenv(config.ENV_AUTO_PUBLISH, "yes")
    monkeypatch.setenv(config.ENV_MAX_GEN_PER_HOUR, "9")
    assert config.browser_headless() is True
    assert config.auto_publish() is True
    assert config.max_generations_per_hour() == 9


def test_int_env_invalid_falls_back(monkeypatch, tmp_path):
    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))
    monkeypatch.setenv(config.ENV_MAX_GEN_PER_DAY, "not-a-number")
    assert config.max_generations_per_day() == 20


def test_nothing_writes_into_repo(monkeypatch, tmp_path):
    # Sanity: with the override set, the resolved root is inside tmp_path.
    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))
    assert Path(config.jobs_dir()).is_relative_to(tmp_path)
