"""RateLimiter math + persistence, with an injected clock."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from social_video_factory.rate_limit import RateLimiter


@pytest.fixture(autouse=True)
def _tmp_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("SOCIAL_FACTORY_DATA_DIR", str(tmp_path / "data"))
    # Deterministic, generous caps unless a test overrides them.
    monkeypatch.setenv("SOCIAL_FACTORY_BROWSER_MAX_GENERATIONS_PER_HOUR", "3")
    monkeypatch.setenv("SOCIAL_FACTORY_BROWSER_MAX_GENERATIONS_PER_DAY", "20")
    monkeypatch.setenv("SOCIAL_FACTORY_BROWSER_MIN_SECONDS_BETWEEN_GENERATIONS", "0")
    monkeypatch.setenv("SOCIAL_FACTORY_BROWSER_REQUIRE_HUMAN_CONFIRM_EVERY", "10")
    return tmp_path


class FakeClock:
    """A mutable injected clock."""

    def __init__(self, start: datetime):
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now = self.now + timedelta(**kwargs)


def _base() -> datetime:
    return datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)


def test_hourly_cap_denies_cap_plus_one(monkeypatch):
    clock = FakeClock(_base())
    rl = RateLimiter(now=clock)
    # 3 allowed within the hour, the 4th denied.
    for _ in range(3):
        assert rl.check().allowed is True
        rl.record()
        clock.advance(minutes=1)
    decision = rl.check()
    assert decision.allowed is False
    assert "hourly cap" in decision.reason


def test_hourly_cap_recovers_after_an_hour(monkeypatch):
    clock = FakeClock(_base())
    rl = RateLimiter(now=clock)
    for _ in range(3):
        rl.record()
        clock.advance(minutes=1)
    assert rl.check().allowed is False
    # Move past the hour window of the oldest entries.
    clock.advance(hours=1, minutes=1)
    assert rl.check().allowed is True


def test_daily_cap_denies(monkeypatch):
    monkeypatch.setenv("SOCIAL_FACTORY_BROWSER_MAX_GENERATIONS_PER_HOUR", "0")
    monkeypatch.setenv("SOCIAL_FACTORY_BROWSER_MAX_GENERATIONS_PER_DAY", "2")
    clock = FakeClock(_base())
    rl = RateLimiter(now=clock)
    rl.record()
    clock.advance(minutes=30)
    rl.record()
    clock.advance(minutes=30)
    decision = rl.check()
    assert decision.allowed is False
    assert "daily cap" in decision.reason


def test_min_gap_denies_then_allows(monkeypatch):
    monkeypatch.setenv("SOCIAL_FACTORY_BROWSER_MIN_SECONDS_BETWEEN_GENERATIONS", "180")
    clock = FakeClock(_base())
    rl = RateLimiter(now=clock)
    rl.record()
    clock.advance(seconds=60)  # < 180
    decision = rl.check()
    assert decision.allowed is False
    assert "minimum gap" in decision.reason
    clock.advance(seconds=130)  # now > 180 total
    assert rl.check().allowed is True


def test_prunes_entries_older_than_a_day(monkeypatch):
    monkeypatch.setenv("SOCIAL_FACTORY_BROWSER_MAX_GENERATIONS_PER_HOUR", "0")
    monkeypatch.setenv("SOCIAL_FACTORY_BROWSER_MAX_GENERATIONS_PER_DAY", "5")
    clock = FakeClock(_base())
    rl = RateLimiter(now=clock)
    rl.record()
    rl.record()
    # Jump forward more than a day; old entries should be pruned on load.
    clock.advance(days=1, hours=1)
    decision = rl.check()
    assert decision.allowed is True
    # Re-load and confirm pruning persisted (a fresh limiter reads the file).
    rl.record()
    state = RateLimiter(now=clock)._load()
    assert len(state["generations"]) == 1  # only the just-recorded one survives


def test_needs_human_confirm_cadence(monkeypatch):
    monkeypatch.setenv("SOCIAL_FACTORY_BROWSER_REQUIRE_HUMAN_CONFIRM_EVERY", "2")
    monkeypatch.setenv("SOCIAL_FACTORY_BROWSER_MAX_GENERATIONS_PER_HOUR", "0")
    monkeypatch.setenv("SOCIAL_FACTORY_BROWSER_MAX_GENERATIONS_PER_DAY", "0")
    clock = FakeClock(_base())
    rl = RateLimiter(now=clock)
    # total_count starts at 0 → NO confirm before the first generation (the
    # total_count > 0 guard); otherwise a non-interactive confirm would decline
    # and the first automated generation could never start.
    assert rl.check().needs_human_confirm is False
    rl.record()  # total_count = 1
    assert rl.check().needs_human_confirm is False
    rl.record()  # total_count = 2 → checkpoint before the 3rd generation
    assert rl.check().needs_human_confirm is True
    rl.record()  # total_count = 3
    assert rl.check().needs_human_confirm is False


def test_persistence_round_trip(monkeypatch):
    clock = FakeClock(_base())
    rl = RateLimiter(now=clock)
    rl.record()
    clock.advance(minutes=1)
    rl.record()
    # A brand-new limiter (same clock/data dir) sees the persisted state.
    fresh = RateLimiter(now=clock)
    state = fresh._load()
    assert state["total_count"] == 2
    assert len(state["generations"]) == 2
