"""Preflight doctor checks — structured, secret-free."""

from __future__ import annotations

import pytest

from social_video_factory import config, doctor


@pytest.fixture(autouse=True)
def _tmp_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SOCIAL_FACTORY_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def _by_name(checks):
    return {c.name: c for c in checks}


def test_unconfigured_env_flags_failures(monkeypatch):
    # Nothing configured: target URL + flow profile should FAIL.
    monkeypatch.delenv("SOCIAL_FACTORY_FLOW_URL", raising=False)
    monkeypatch.delenv("SOCIAL_FACTORY_GEMINI_URL", raising=False)
    checks = doctor.run_checks()
    by = _by_name(checks)
    assert by["target_url"].level == doctor.FAIL
    assert by["flow_profile"].level == doctor.FAIL
    _, _, fail = doctor.summarize(checks)
    assert fail >= 1


def test_seeded_profile_and_url_pass(monkeypatch):
    monkeypatch.setenv("SOCIAL_FACTORY_FLOW_URL", "https://example.test/flow")
    # Seed the flow profile dir with a file so it looks initialized.
    (config.profile_dir() / "Default").mkdir(parents=True, exist_ok=True)
    (config.profile_dir() / "Default" / "Cookies").write_text("x", encoding="utf-8")
    checks = _by_name(doctor.run_checks())
    assert checks["target_url"].level == doctor.OK
    assert checks["flow_profile"].level == doctor.OK


def test_human_confirm_warns_when_nonzero(monkeypatch):
    monkeypatch.setenv("SOCIAL_FACTORY_BROWSER_REQUIRE_HUMAN_CONFIRM_EVERY", "10")
    checks = _by_name(doctor.run_checks())
    assert checks["human_confirm"].level == doctor.WARN

    monkeypatch.setenv("SOCIAL_FACTORY_BROWSER_REQUIRE_HUMAN_CONFIRM_EVERY", "0")
    checks = _by_name(doctor.run_checks())
    assert checks["human_confirm"].level == doctor.OK


def test_no_secret_values_in_details(monkeypatch):
    # A token value must never be echoed in the report details.
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "SECRETTOKENVALUE")
    monkeypatch.setenv("TELEGRAM_HOME_CHANNEL", "123")
    checks = doctor.run_checks()
    assert all("SECRETTOKENVALUE" not in c.detail for c in checks)
