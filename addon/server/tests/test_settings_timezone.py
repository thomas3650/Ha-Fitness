"""Tests for the settings of step 4: the timezone, the dev flag, the scheduler interval and the Supervisor token."""

from datetime import UTC, datetime, timedelta
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from ha_fitness_server.clock import SystemClock
from ha_fitness_server.settings import Settings
import pytest

from tests.conftest import FrozenClock

_VARS = (
    "HA_FITNESS_TIMEZONE",
    "TZ",
    "HA_FITNESS_DEV",
    "SUPERVISOR_TOKEN",
    "HA_FITNESS_HA_URL",
    "HA_FITNESS_HA_TOKEN_FILE",
)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Remove the variables these settings read from the environment."""
    for name in _VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_timezone_precedence(
    env: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`HA_FITNESS_TIMEZONE` wins over `TZ`; `TZ` alone is used; neither, or an unknown name, gives UTC."""
    env.setenv("HA_FITNESS_TIMEZONE", "Europe/Copenhagen")
    env.setenv("TZ", "America/New_York")
    assert Settings.from_env().timezone == ZoneInfo("Europe/Copenhagen")

    env.delenv("HA_FITNESS_TIMEZONE")
    assert Settings.from_env().timezone == ZoneInfo("America/New_York")

    env.delenv("TZ")
    assert Settings.from_env().timezone == ZoneInfo("UTC")

    env.setenv("HA_FITNESS_TIMEZONE", "Mars/Base")
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert Settings.from_env().timezone == ZoneInfo("UTC")
    assert any(record.levelno == logging.WARNING for record in caplog.records)


def test_new_settings_defaults(env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The new fields have defaults, and the environment sets the dev flag and the Supervisor token."""
    settings = Settings(port=0, data_dir=tmp_path)
    assert settings.timezone == ZoneInfo("UTC")
    assert settings.dev is False
    assert settings.scheduler_interval == 60.0
    assert settings.supervisor_token is None

    from_env = Settings.from_env()
    assert from_env.dev is False
    assert from_env.supervisor_token is None

    env.setenv("HA_FITNESS_DEV", "1")
    env.setenv("SUPERVISOR_TOKEN", "supervisor-secret")
    from_env = Settings.from_env()
    assert from_env.dev is True
    assert from_env.supervisor_token == "supervisor-secret"
    # Step 3's HA access keeps reading the same token.
    assert from_env.ha_token == "supervisor-secret"

    env.setenv("HA_FITNESS_DEV", "yes")
    assert Settings.from_env().dev is False


def test_system_clock_is_aware_utc() -> None:
    """The system clock returns the current time, aware and in UTC."""
    before = datetime.now(UTC)
    now = SystemClock().now()
    after = datetime.now(UTC)
    assert now.utcoffset() == timedelta(0)
    assert before <= now <= after


def test_frozen_clock_set_and_advance() -> None:
    """The test clock stands still until a test sets or advances it."""
    start = datetime(2026, 10, 21, 6, 0, tzinfo=UTC)
    clock = FrozenClock(start)
    assert clock.now() == start
    assert clock.now() == start
    clock.advance(timedelta(minutes=5))
    assert clock.now() == start + timedelta(minutes=5)
    later = datetime(2026, 10, 22, 7, 0, tzinfo=UTC)
    clock.set(later)
    assert clock.now() == later
