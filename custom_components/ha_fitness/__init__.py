"""The HA Fitness integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_integration

from .cards import async_register_cards, async_unregister_cards
from .const import DEFAULT_URL, DOMAIN, UNIQUE_ID
from .coordinator import FitnessCoordinator

type HaFitnessConfigEntry = ConfigEntry[FitnessCoordinator]
"""The entry's runtime data is its coordinator, which also knows the integration's version."""


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate a version 1 entry (0.1.0: no URL, no unique id) to version 2.

    Under the Supervisor, the add-on's next discovery then corrects the URL.
    """
    if entry.version == 1:
        hass.config_entries.async_update_entry(
            entry, data={CONF_URL: DEFAULT_URL}, unique_id=UNIQUE_ID, version=2
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HaFitnessConfigEntry) -> bool:
    """Set up HA Fitness from a config entry.

    It doesn't wait for the add-on: the coordinator connects in the background and retries.
    """
    integration = await async_get_integration(hass, DOMAIN)
    version = str(integration.version)
    await async_register_cards(hass, version)
    coordinator = FitnessCoordinator(
        hass, entry, async_get_clientsession(hass), entry.data[CONF_URL], version
    )
    entry.runtime_data = coordinator
    coordinator.async_start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HaFitnessConfigEntry) -> bool:
    """Unload a config entry; Home Assistant then cancels the connection task."""
    coordinator = entry.runtime_data
    coordinator.async_stop()
    async_unregister_cards(hass, coordinator.integration_version)
    return True
