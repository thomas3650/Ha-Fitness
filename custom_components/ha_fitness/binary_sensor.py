"""The binary sensor: on while any training day is open (spec §4.3)."""

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HaFitnessConfigEntry
from .coordinator import FitnessCoordinator
from .entity import FitnessEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaFitnessConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the binary sensor."""
    async_add_entities([TrainingOpenSensor(entry.runtime_data)])


class TrainingOpenSensor(FitnessEntity, BinarySensorEntity):
    """On while any training day is open (due or late)."""

    def __init__(self, coordinator: FitnessCoordinator) -> None:
        """Set up the binary sensor."""
        super().__init__(coordinator, "binary_sensor", "training_open")

    @property
    def is_on(self) -> bool:
        """Return whether any day is open."""
        return bool((self.coordinator.today or {}).get("open"))
