"""Tests for serving the cards bundle to the frontend."""

from pathlib import Path
from typing import Any

from homeassistant.components import frontend
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_fitness.const import CARDS_FILE, FRONTEND_URL_BASE

CARDS_URL_PREFIX = f"{FRONTEND_URL_BASE}/{CARDS_FILE}?v="


def _cards_urls(hass: HomeAssistant) -> list[str]:
    """Return the extra module URLs that load the cards bundle."""
    return [
        url
        for url in hass.data[frontend.DATA_EXTRA_MODULE_URL].urls
        if url.startswith(CARDS_URL_PREFIX)
    ]


async def test_setup_serves_cards_bundle(
    hass: HomeAssistant,
    hass_client: Any,
    setup_entry: MockConfigEntry,
    cards_bundle: Path,
) -> None:
    """After setup, the cards bundle is served over HTTP."""
    client = await hass_client()
    response = await client.get(f"{FRONTEND_URL_BASE}/{CARDS_FILE}")
    assert response.status == 200
    assert "customElements" in await response.text()


async def test_setup_adds_cards_module_url(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    """After setup, the frontend loads the cards bundle as a module, versioned."""
    assert setup_entry.state is ConfigEntryState.LOADED
    assert _cards_urls(hass) == [f"{CARDS_URL_PREFIX}0.0.0"]


async def test_unload_removes_cards_module_url(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    """Unloading the entry stops the frontend from loading the cards."""
    assert await hass.config_entries.async_unload(setup_entry.entry_id)
    await hass.async_block_till_done()

    assert setup_entry.state is ConfigEntryState.NOT_LOADED
    assert _cards_urls(hass) == []


async def test_reload_serves_cards_again(
    hass: HomeAssistant, hass_client: Any, setup_entry: MockConfigEntry
) -> None:
    """A reload in the same run sets up again, with the cards loaded once."""
    assert await hass.config_entries.async_reload(setup_entry.entry_id)
    await hass.async_block_till_done()

    assert setup_entry.state is ConfigEntryState.LOADED
    assert _cards_urls(hass) == [f"{CARDS_URL_PREFIX}0.0.0"]
    client = await hass_client()
    response = await client.get(f"{FRONTEND_URL_BASE}/{CARDS_FILE}")
    assert response.status == 200
