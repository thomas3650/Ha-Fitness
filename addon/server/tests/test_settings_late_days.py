"""Tests for the `late_days` setting (today-ahead spec §2.1.5): the add-on option file, then the environment."""

import json
import logging
from pathlib import Path
from typing import Any

from ha_fitness_server.settings import Settings
import pytest

_VARS = (
    "HA_FITNESS_LATE_DAYS",
    "HA_FITNESS_DATA_DIR",
    "SUPERVISOR_TOKEN",
    "HA_FITNESS_HA_URL",
    "HA_FITNESS_HA_TOKEN_FILE",
)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    """Clear the variables these settings read, and point the data folder at `tmp_path`."""
    for name in _VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HA_FITNESS_DATA_DIR", str(tmp_path))
    return monkeypatch


def _options(folder: Path, body: Any) -> None:
    """Write the add-on's options file with `body` as JSON."""
    (folder / "options.json").write_text(json.dumps(body), encoding="utf-8")


def _warned(caplog: pytest.LogCaptureFixture) -> bool:
    """Return whether a warning was logged."""
    return any(record.levelno == logging.WARNING for record in caplog.records)


def test_default_is_two(env: pytest.MonkeyPatch) -> None:
    """With no options file and no variable, `late_days` is 2."""
    assert Settings.from_env().late_days == 2


def test_options_file_sets_it(env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The add-on's `options.json` in the data folder gives `late_days`."""
    _options(tmp_path, {"late_days": 4})
    assert Settings.from_env().late_days == 4


def test_options_file_without_the_key(env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An options file without `late_days` gives the default, without a warning."""
    _options(tmp_path, {})
    assert Settings.from_env().late_days == 2


def test_variable_wins_over_the_file(env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`HA_FITNESS_LATE_DAYS` wins over the options file."""
    _options(tmp_path, {"late_days": 4})
    env.setenv("HA_FITNESS_LATE_DAYS", "1")
    assert Settings.from_env().late_days == 1


@pytest.mark.parametrize("value", [7, -1, "3", 2.5, True, None], ids=str)
def test_invalid_file_value_is_ignored(
    env: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    value: Any,
) -> None:
    """A value outside 0-6, not an integer, or a boolean is ignored with a warning."""
    _options(tmp_path, {"late_days": value})
    with caplog.at_level(logging.WARNING):
        assert Settings.from_env().late_days == 2
    assert _warned(caplog)


@pytest.mark.parametrize("body", ["not json", "[1, 2]"], ids=["broken", "a list"])
def test_unreadable_file_is_ignored(
    env: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    body: str,
) -> None:
    """An options file that isn't a JSON object is ignored with a warning."""
    (tmp_path / "options.json").write_text(body, encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert Settings.from_env().late_days == 2
    assert _warned(caplog)


@pytest.mark.parametrize("value", ["7", "-1", "two", "true", "2.5"])
def test_invalid_variable_falls_back_to_the_file(
    env: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    value: str,
) -> None:
    """An invalid `HA_FITNESS_LATE_DAYS` is ignored with a warning: the file's value, then 2."""
    env.setenv("HA_FITNESS_LATE_DAYS", value)
    with caplog.at_level(logging.WARNING):
        assert Settings.from_env().late_days == 2
    assert _warned(caplog)
    _options(tmp_path, {"late_days": 5})
    assert Settings.from_env().late_days == 5


def test_zero_and_six_are_valid(env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Both ends of 0-6 are taken, from the file and from the variable."""
    _options(tmp_path, {"late_days": 0})
    assert Settings.from_env().late_days == 0
    env.setenv("HA_FITNESS_LATE_DAYS", "6")
    assert Settings.from_env().late_days == 6
