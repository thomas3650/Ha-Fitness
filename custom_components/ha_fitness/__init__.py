"""The HA Fitness integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .cards import async_register_cards, async_unregister_cards
from .const import DEFAULT_URL, DEVICE_NAME, DOMAIN, SIGNAL_UPDATE, UNIQUE_ID
from .coordinator import FitnessCoordinator
from .services import async_setup_services
from .websocket_api import async_setup_websocket_api

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]

type HaFitnessConfigEntry = ConfigEntry[FitnessCoordinator]
"""The entry's runtime data is its coordinator, which also knows the integration's version."""


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the service and the card's subscription, which exist without a loaded entry."""
    async_setup_services(hass)
    async_setup_websocket_api(hass)
    return True


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
    # The device exists before the first hello, which sets its software version.
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=DEVICE_NAME,
        entry_type=dr.DeviceEntryType.SERVICE,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.async_start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HaFitnessConfigEntry) -> bool:
    """Unload a config entry; Home Assistant then cancels the connection task."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # The entry stays up, so the connection does too.
        return False
    coordinator = entry.runtime_data
    coordinator.async_stop()
    async_unregister_cards(hass, coordinator.integration_version)
    # The entry is no longer loaded (it is being unloaded), so the card's subscription sends null.
    async_dispatcher_send(hass, SIGNAL_UPDATE)
    return True
