"""Fixtures for the HA Fitness tests."""

from collections.abc import AsyncGenerator
from pathlib import Path

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
import pytest
from pytest_aiohttp import AiohttpServer
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_fitness import cards
from custom_components.ha_fitness.const import CARDS_FILE, DOMAIN

from .fake_addon import FakeAddon
from .music_workout import workout  # noqa: F401 (the fixture, for the music tests)

# A stand-in for the bundle Task 5 builds; the real frontend/ folder is never used in tests.
FAKE_BUNDLE = (
    "customElements.define('ha-fitness-test-card', class extends HTMLElement {});\n"
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load integrations from custom_components in every test."""


@pytest.fixture
def cards_bundle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Serve the cards from a temporary folder that holds a small bundle."""
    bundle = tmp_path / CARDS_FILE
    bundle.write_text(FAKE_BUNDLE, encoding="utf-8")
    monkeypatch.setattr(cards, "FRONTEND_DIR", tmp_path)
    return bundle


@pytest.fixture
async def fake_addon(socket_enabled: None, aiohttp_server: AiohttpServer) -> FakeAddon:
    """A fake add-on on 127.0.0.1; sockets are on, and phcc still allows only that host."""
    addon = FakeAddon()
    server = await aiohttp_server(addon.app)
    addon.url = f"http://127.0.0.1:{server.port}"
    return addon


@pytest.fixture
def config_entry(hass: HomeAssistant, fake_addon: FakeAddon) -> MockConfigEntry:
    """The integration's config entry (version 2), pointing at the fake add-on; added, not set up."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HA Fitness",
        data={"url": fake_addon.url},
        unique_id="ha_fitness",
        version=2,
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry, cards_bundle: Path
) -> AsyncGenerator[MockConfigEntry]:
    """The config entry, set up (with the cards served from the temporary bundle).

    It is unloaded afterwards, so its connection to the fake add-on leaves no task or timer behind.
    """
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    yield config_entry
    if config_entry.state is ConfigEntryState.LOADED:
        assert await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()
