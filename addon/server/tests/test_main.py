"""Tests for `python -m ha_fitness_server`: `main()` prepares the data folder, then starts uvicorn."""

from pathlib import Path
from typing import Any

from ha_fitness_server import __main__ as entry
import pytest
import uvicorn

_VARS = (
    "HA_FITNESS_PORT",
    "HA_FITNESS_DATA_DIR",
    "HA_FITNESS_HA_URL",
    "HA_FITNESS_HA_TOKEN_FILE",
    "HA_FITNESS_MEDIA_BASE_URL",
    "HA_FITNESS_TIMEZONE",
    "HA_FITNESS_DEV",
    "SUPERVISOR_TOKEN",
    "TZ",
)


def test_main_creates_the_data_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`main()` creates a missing data folder, parents included, before uvicorn starts on the configured port."""
    for name in _VARS:
        monkeypatch.delenv(name, raising=False)
    data_dir = tmp_path / "missing" / "data"
    monkeypatch.setenv("HA_FITNESS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("HA_FITNESS_PORT", "8799")
    calls: list[dict[str, Any]] = []

    def fake_run(app: object, **kwargs: Any) -> None:
        calls.append({"folder_existed": data_dir.is_dir(), **kwargs})

    monkeypatch.setattr(uvicorn, "run", fake_run)
    entry.main()
    assert data_dir.is_dir()
    assert calls == [{"folder_existed": True, "host": "0.0.0.0", "port": 8799}]
