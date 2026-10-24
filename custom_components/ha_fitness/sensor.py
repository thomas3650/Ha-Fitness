"""The sensors: training today and the next training day (spec §4.3), and the stats per person.

The stats sensors are the stats spec §5.1's: four per person, made and removed with the people.
"""

import asyncio
from datetime import date
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback, split_entity_id, valid_entity_id
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import (
    AddConfigEntryEntitiesCallback,
    EntityPlatform,
    async_get_current_platform,
)

from . import HaFitnessConfigEntry
from .const import DOMAIN
from .coordinator import FitnessCoordinator
from .entity import FitnessEntity

TODAY_OPTIONS = ["none", "due", "late"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HaFitnessConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the two sensors, and follow the people for the stats sensors."""
    coordinator = entry.runtime_data
    async_add_entities([TodaySensor(coordinator), NextTrainingDaySensor(coordinator)])
    people = PeopleSensors(hass, entry, async_get_current_platform())
    entry.async_on_unload(coordinator.async_add_listener(people.async_schedule_sync))
    people.async_schedule_sync()


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


class PeopleSensors:
    """Keep four stats sensors per person in step with the add-on's people.

    On each update while the stats are available (never on a disconnect, which keeps the last
    stats), the registry's person sensors are diffed against the people. The sensors of people who
    are gone are removed, and only once they are gone from the state machine are new people's
    sensors added, so a person re-added with a new add-on id keeps the entity ids (no `_2`). The
    diff runs one at a time, and only when the people (their ids and person entities) changed.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: HaFitnessConfigEntry,
        platform: EntityPlatform,
    ) -> None:
        """Set up the diff; no sensors exist before the first stats."""
        self.hass = hass
        self.entry = entry
        self.coordinator = entry.runtime_data
        self.platform = platform
        self.prefix = f"{entry.entry_id}_person_"
        # The sensors added in this run, by unique id (added or about to be).
        self.entities: dict[str, PersonStatsSensor] = {}
        self.lock = asyncio.Lock()
        # The people the last diff ran for, by id and person entity; None before the first.
        self.synced: list[tuple[Any, Any]] | None = None

    @callback
    def async_schedule_sync(self) -> None:
        """Run the diff in the background while the stats are available."""
        if self.coordinator.stats_available:
            self.entry.async_create_background_task(
                self.hass, self._async_sync(), f"{DOMAIN} stats sensors"
            )

    def _wanted(self) -> dict[str, PersonStatsSensor | None]:
        """Return the unique ids the current people need, with a sensor for those not made yet."""
        wanted: dict[str, PersonStatsSensor | None] = {}
        for person in (self.coordinator.stats or {}).get("people", []):
            entity_id = person.get("person_entity_id")
            if not isinstance(entity_id, str) or not valid_entity_id(entity_id):
                continue
            for sensor_class in PERSON_SENSORS:
                unique_id = f"{self.prefix}{person['id']}_{sensor_class.stat}"
                wanted[unique_id] = (
                    None
                    if unique_id in self.entities
                    else sensor_class(
                        self.coordinator,
                        person["id"],
                        split_entity_id(entity_id)[1],
                        str(person.get("name", "")),
                    )
                )
        return wanted

    async def _async_sync(self) -> None:
        async with self.lock:
            if not self.coordinator.stats_available:
                return
            people = [
                (person.get("id"), person.get("person_entity_id"))
                for person in (self.coordinator.stats or {}).get("people", [])
            ]
            if people == self.synced:
                return
            wanted = self._wanted()
            registry = er.async_get(self.hass)
            stale = {
                registry_entry.unique_id: registry_entry.entity_id
                for registry_entry in er.async_entries_for_config_entry(
                    registry, self.entry.entry_id
                )
                if registry_entry.unique_id.startswith(self.prefix)
                and registry_entry.unique_id not in wanted
            }
            for unique_id, entity_id in stale.items():
                entity = self.entities.pop(unique_id, None)
                if entity is not None and entity.hass is not None:
                    # Removes the state too, so the entity id is free before anything is added.
                    await entity.async_remove(force_remove=True)
                elif self.hass.states.get(entity_id) is not None:
                    # The unavailable state a previous run left behind. A sensor the user
                    # disabled was never added, and has no state.
                    self.hass.states.async_remove(entity_id)
                registry.async_remove(entity_id)
            new = {
                unique_id: entity
                for unique_id, entity in wanted.items()
                if entity is not None
            }
            if new:
                self.entities.update(new)
                await self.platform.async_add_entities(list(new.values()))
            self.synced = people


class PersonStatsSensor(FitnessEntity, SensorEntity):
    """One of a person's stats; available while the stats are, and the person is in them."""

    stat: str

    def __init__(
        self,
        coordinator: FitnessCoordinator,
        person_id: int,
        object_id: str,
        name: str,
    ) -> None:
        """Set the ids from the person entity and the add-on person, and the name's person.

        HA caches the name, so a rename in the add-on shows after the entry is reloaded.
        """
        super().__init__(
            coordinator,
            "sensor",
            self.stat,
            entity_key=f"{object_id}_{self.stat}",
            unique_key=f"person_{person_id}_{self.stat}",
        )
        self.person_id = person_id
        self._attr_translation_placeholders = {"person": name}

    def _person(self) -> dict[str, Any] | None:
        for person in (self.coordinator.stats or {}).get("people", []):
            if person.get("id") == self.person_id:
                found: dict[str, Any] = person
                return found
        return None

    def _totals(self, period: str) -> dict[str, int]:
        totals: dict[str, int] = (self._person() or {}).get(period, {})
        return totals

    @property
    def available(self) -> bool:
        """Return whether the stats are available and still hold this person."""
        return self.coordinator.stats_available and self._person() is not None


class StreakSensor(PersonStatsSensor):
    """The person's streak, in days, with no unit: a translated unit would show in English (ha-notes.md)."""

    stat = "streak"
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int | None:
        """Return the streak."""
        streak: int | None = (self._person() or {}).get("streak")
        return streak


class DoneSensor(PersonStatsSensor):
    """All-time done, with this month and the extra sessions as attributes."""

    stat = "done"
    _attr_state_class = SensorStateClass.TOTAL
    _unrecorded_attributes = frozenset({"this_month", "extra", "extra_this_month"})

    @property
    def native_value(self) -> int | None:
        """Return the days and extra sessions done, all time."""
        return self._totals("all_time").get("done")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return done this month, and the extra sessions of all time and this month."""
        all_time, this_month = self._totals("all_time"), self._totals("this_month")
        return {
            "this_month": this_month.get("done"),
            "extra": all_time.get("extra"),
            "extra_this_month": this_month.get("extra"),
        }


def _missed(totals: dict[str, int]) -> int | None:
    """Return missed plus skipped, the card's one number (stats spec §3.4)."""
    if "missed" not in totals or "skipped" not in totals:
        return None
    return totals["missed"] + totals["skipped"]


class MissedSensor(PersonStatsSensor):
    """All-time missed plus skipped, with this month and the skips as attributes."""

    stat = "missed"
    _attr_state_class = SensorStateClass.TOTAL
    _unrecorded_attributes = frozenset({"this_month", "skipped", "skipped_this_month"})

    @property
    def native_value(self) -> int | None:
        """Return the days missed or skipped, all time."""
        return _missed(self._totals("all_time"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return missed plus skipped this month, and the skips of all time and this month."""
        all_time, this_month = self._totals("all_time"), self._totals("this_month")
        return {
            "this_month": _missed(this_month),
            "skipped": all_time.get("skipped"),
            "skipped_this_month": this_month.get("skipped"),
        }


def _minutes(totals: dict[str, int]) -> int | None:
    """Return the time trained in whole minutes, rounded down."""
    seconds = totals.get("time_trained")
    return None if seconds is None else seconds // 60


class TimeTrainedSensor(PersonStatsSensor):
    """All-time time trained in minutes, with this month as an attribute."""

    stat = "time_trained"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_state_class = SensorStateClass.TOTAL
    _unrecorded_attributes = frozenset({"this_month"})

    @property
    def native_value(self) -> int | None:
        """Return the time trained, all time."""
        return _minutes(self._totals("all_time"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the time trained this month."""
        return {"this_month": _minutes(self._totals("this_month"))}


PERSON_SENSORS: tuple[type[PersonStatsSensor], ...] = (
    StreakSensor,
    DoneSensor,
    MissedSensor,
    TimeTrainedSensor,
)
