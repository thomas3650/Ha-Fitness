"""Tests for serving the cards bundle to the frontend."""

from pathlib import Path

from homeassistant.components import frontend
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.ha_fitness.const import CARDS_FILE, DOMAIN, FRONTEND_URL_BASE

CARDS_URL_PREFIX = f"{FRONTEND_URL_BASE}/{CARDS_FILE}?v="


async def _expected_cards_url(hass: HomeAssistant) -> str:
    """Return the cards URL for the manifest's version (release-please bumps it)."""
    integration = await async_get_integration(hass, DOMAIN)
    return f"{CARDS_URL_PREFIX}{integration.version}"


def _cards_urls(hass: HomeAssistant) -> list[str]:
    """Return the extra module URLs that load the cards bundle."""
    return [
        url
        for url in hass.data[frontend.DATA_EXTRA_MODULE_URL].urls
        if url.startswith(CARDS_URL_PREFIX)
    ]


async def test_setup_serves_cards_bundle(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    setup_entry: MockConfigEntry,
    cards_bundle: Path,
) -> None:
    """After setup, the cards bundle is served over HTTP."""
    client = await hass_client()
    response = await client.get(f"{FRONTEND_URL_BASE}/{CARDS_FILE}")
    assert response.status == 200
    assert await response.text() == cards_bundle.read_text(encoding="utf-8")


async def test_setup_adds_cards_module_url(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    """After setup, the frontend loads the cards bundle as a module, versioned."""
    assert setup_entry.state is ConfigEntryState.LOADED
    assert _cards_urls(hass) == [await _expected_cards_url(hass)]


async def test_unload_removes_cards_module_url(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    """Unloading the entry stops the frontend from loading the cards."""
    assert await hass.config_entries.async_unload(setup_entry.entry_id)
    await hass.async_block_till_done()

    assert setup_entry.state is ConfigEntryState.NOT_LOADED
    assert _cards_urls(hass) == []


async def test_reload_serves_cards_again(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    setup_entry: MockConfigEntry,
) -> None:
    """A reload in the same run sets up again, with the cards loaded once."""
    assert await hass.config_entries.async_reload(setup_entry.entry_id)
    await hass.async_block_till_done()

    assert setup_entry.state is ConfigEntryState.LOADED
    assert _cards_urls(hass) == [await _expected_cards_url(hass)]
    client = await hass_client()
    response = await client.get(f"{FRONTEND_URL_BASE}/{CARDS_FILE}")
    assert response.status == 200
