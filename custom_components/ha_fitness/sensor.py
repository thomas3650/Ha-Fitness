"""The sensors: training today, and the next training day (spec §4.3)."""

from datetime import date
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HaFitnessConfigEntry
from .coordinator import FitnessCoordinator
from .entity import FitnessEntity

TODAY_OPTIONS = ["none", "due", "late"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaFitnessConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the two sensors."""
    coordinator = entry.runtime_data
    async_add_entities([TodaySensor(coordinator), NextTrainingDaySensor(coordinator)])


class TodaySensor(FitnessEntity, SensorEntity):
    """Due if any open day is due, else late if any is late, else none."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = TODAY_OPTIONS
    _unrecorded_attributes = frozenset({"training_days"})

    def __init__(self, coordinator: FitnessCoordinator) -> None:
        """Set up the sensor."""
        super().__init__(coordinator, "sensor", "today")

    def _open(self) -> list[dict[str, Any]]:
        open_days: list[dict[str, Any]] = (self.coordinator.today or {}).get("open", [])
        return open_days

    @property
    def native_value(self) -> str:
        """Return none, due or late."""
        states = {day.get("state") for day in self._open()}
        if "due" in states:
            return "due"
        if "late" in states:
            return "late"
        return "none"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the open days, as the add-on sent them."""
        return {"training_days": self._open()}


class NextTrainingDaySensor(FitnessEntity, SensorEntity):
    """The first date after today on which an active program trains, or unknown."""

    _attr_device_class = SensorDeviceClass.DATE
    _unrecorded_attributes = frozenset({"programs"})

    def __init__(self, coordinator: FitnessCoordinator) -> None:
        """Set up the sensor."""
        super().__init__(coordinator, "sensor", "next_training_day")

    def _next(self) -> dict[str, Any]:
        next_day: dict[str, Any] | None = (self.coordinator.today or {}).get("next")
        return next_day or {}

    @property
    def native_value(self) -> date | None:
        """Return the next training day's date, or None when no program is active."""
        if isinstance(value := self._next().get("date"), str):
            return date.fromisoformat(value)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the names of the programs that train on the next training day."""
        return {"programs": self._next().get("programs", [])}
