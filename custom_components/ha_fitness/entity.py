"""The base of the HA Fitness entities: one device, fed by the coordinator's pushes."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .coordinator import FitnessCoordinator


class FitnessEntity(Entity):
    """An entity of the HA Fitness device; unavailable unless a supported add-on has sent today."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, coordinator: FitnessCoordinator, platform: str, key: str
    ) -> None:
        """Set the explicit entity id (so a Danish HA keeps the English one) and the unique id."""
        self.coordinator = coordinator
        entry_id = coordinator.entry.entry_id
        self.entity_id = f"{platform}.{DOMAIN}_{key}"
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry_id}_{key}"
        # The device itself, with the add-on's version, is made at setup (see __init__.py).
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry_id)})

    @property
    def available(self) -> bool:
        """Return whether a supported add-on is connected and has sent today."""
        return self.coordinator.available

    async def async_added_to_hass(self) -> None:
        """Write the state on every change the coordinator reports."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )
