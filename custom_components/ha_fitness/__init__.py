"""The HA Fitness integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .cards import async_register_cards, async_unregister_cards
from .const import DEFAULT_URL, DOMAIN, UNIQUE_ID

type HaFitnessConfigEntry = ConfigEntry[str]
"""The entry's runtime data is the version the cards bundle was registered with."""


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
    """Set up HA Fitness from a config entry."""
    integration = await async_get_integration(hass, DOMAIN)
    version = str(integration.version)
    await async_register_cards(hass, version)
    entry.runtime_data = version
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HaFitnessConfigEntry) -> bool:
    """Unload a config entry."""
    async_unregister_cards(hass, entry.runtime_data)
    return True
