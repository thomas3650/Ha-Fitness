"""Tests for the health endpoint and the settings."""

from pathlib import Path

from ha_fitness_server import __version__
from ha_fitness_server.settings import Settings
import httpx
import pytest


async def test_health_reports_version_and_api_version(
    client: httpx.AsyncClient,
) -> None:
    """The health endpoint reports the server and API versions."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__, "api_version": 1}


def test_settings_from_env_reads_port_and_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Settings come from the environment."""
    monkeypatch.setenv("HA_FITNESS_PORT", "9999")
    monkeypatch.setenv("HA_FITNESS_DATA_DIR", str(tmp_path / "d"))
    assert Settings.from_env() == Settings(port=9999, data_dir=tmp_path / "d")


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without environment variables the add-on defaults apply."""
    monkeypatch.delenv("HA_FITNESS_PORT", raising=False)
    monkeypatch.delenv("HA_FITNESS_DATA_DIR", raising=False)
    assert Settings.from_env() == Settings(port=8765, data_dir=Path("/data"))
