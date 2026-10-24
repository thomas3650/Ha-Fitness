"""The binary sensors: training open (step 4 spec §4.3) and session running (the workout spec §4)."""

from typing import Any

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
    """Add the binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [TrainingOpenSensor(coordinator), SessionRunningSensor(coordinator)]
    )


class TrainingOpenSensor(FitnessEntity, BinarySensorEntity):
    """On while any training day is open (due or late)."""

    def __init__(self, coordinator: FitnessCoordinator) -> None:
        """Set up the binary sensor."""
        super().__init__(coordinator, "binary_sensor", "training_open")

    @property
    def is_on(self) -> bool:
        """Return whether any day is open."""
        return bool((self.coordinator.today or {}).get("open"))


ACTIVE_STATUSES = ("running", "paused")


class SessionRunningSensor(FitnessEntity, BinarySensorEntity):
    """On while a session is running or paused; off when there is none, or it has finished."""

    _unrecorded_attributes = frozenset({"program", "participants"})

    def __init__(self, coordinator: FitnessCoordinator) -> None:
        """Set up the binary sensor."""
        super().__init__(coordinator, "binary_sensor", "session_running")

    def _active(self) -> dict[str, Any] | None:
        """Return the session view while it is running or paused."""
        session = self.coordinator.session
        if session is not None and session.get("status") in ACTIVE_STATUSES:
            return session
        return None

    @property
    def available(self) -> bool:
        """Return whether the add-on is connected and has sent its session since."""
        return self.coordinator.session_available

    @property
    def is_on(self) -> bool:
        """Return whether a session is running or paused."""
        return self._active() is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the active session's program name and participants, as the add-on sent them."""
        session = self._active() or {}
        return {
            "program": session.get("program_name"),
            "participants": session.get("participants", []),
        }
