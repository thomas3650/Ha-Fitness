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


_HA_VARS = (
    "SUPERVISOR_TOKEN",
    "HA_FITNESS_HA_URL",
    "HA_FITNESS_HA_TOKEN_FILE",
    "HA_FITNESS_MEDIA_BASE_URL",
    "HA_FITNESS_TIMEZONE",
    "TZ",
    "HA_FITNESS_DEV",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Remove the HA and media variables from the environment."""
    for name in _HA_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_settings_from_env_reads_port_and_data_dir(
    clean_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Settings come from the environment."""
    clean_env.setenv("HA_FITNESS_PORT", "9999")
    clean_env.setenv("HA_FITNESS_DATA_DIR", str(tmp_path / "d"))
    assert Settings.from_env() == Settings(port=9999, data_dir=tmp_path / "d")


def test_settings_defaults(clean_env: pytest.MonkeyPatch) -> None:
    """Without environment variables the add-on defaults apply."""
    clean_env.delenv("HA_FITNESS_PORT", raising=False)
    clean_env.delenv("HA_FITNESS_DATA_DIR", raising=False)
    assert Settings.from_env() == Settings(port=8765, data_dir=Path("/data"))


def test_settings_supervisor_token_wins(clean_env: pytest.MonkeyPatch) -> None:
    """Under the Supervisor HA is reached through its proxy with its token."""
    clean_env.setenv("SUPERVISOR_TOKEN", "supervisor-secret")
    clean_env.setenv("HA_FITNESS_HA_URL", "http://ha.test:8123")
    clean_env.setenv("HA_FITNESS_HA_TOKEN_FILE", "/run/ha-token")
    settings = Settings.from_env()
    assert settings.ha_url == "http://supervisor/core"
    assert settings.ha_token == "supervisor-secret"
    assert settings.ha_token_file is None


def test_settings_ha_url_and_token_file(clean_env: pytest.MonkeyPatch) -> None:
    """Outside the Supervisor HA's URL and a token file come from the environment."""
    clean_env.setenv("HA_FITNESS_HA_URL", "http://ha.test:8123")
    clean_env.setenv("HA_FITNESS_HA_TOKEN_FILE", "/run/ha-token")
    settings = Settings.from_env()
    assert settings.ha_url == "http://ha.test:8123"
    assert settings.ha_token is None
    assert settings.ha_token_file == Path("/run/ha-token")


def test_settings_without_ha(clean_env: pytest.MonkeyPatch) -> None:
    """Without any HA variable HA is not configured."""
    settings = Settings.from_env()
    assert settings.ha_url is None
    assert settings.ha_token is None
    assert settings.ha_token_file is None


def test_settings_media_base_url(clean_env: pytest.MonkeyPatch) -> None:
    """The media source defaults to the pinned dataset commit and can be overridden."""
    assert Settings.from_env().media_base_url == (
        "https://raw.githubusercontent.com/hasaneyldrm/exercises-dataset/"
        "7455efae41b330c265e7cd4b78dfa848e7ce5ebd"
    )
    clean_env.setenv("HA_FITNESS_MEDIA_BASE_URL", "http://media.test")
    assert Settings.from_env().media_base_url == "http://media.test"
