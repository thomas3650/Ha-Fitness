"""Tests for the stats sensors, four per person (stats spec §5.1).

Observed through entity states, the entity registry and the loaded translations.
"""

import asyncio
import copy
import logging
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.translation import async_get_translations
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_fitness.const import DOMAIN

from .common import is_open, set_up, unload, wait_for
from .fake_addon import PERSON_STATS, STATS_EMPTY, FakeAddon

KEYS = ("streak", "done", "missed", "time_trained")
# Rounds to let pending work finish before checking that something did not happen.
SETTLE_ROUNDS = 1000

# Bo: every all-time number differs from its this-month number, so a swapped field fails.
BO_STATS: dict[str, Any] = {
    "id": 2,
    "name": "Bo",
    "person_entity_id": "person.bo",
    "streak": 0,
    "all_time": {
        "done": 7,
        "extra": 3,
        "missed": 2,
        "skipped": 3,
        "time_trained": 5999,
    },
    "this_month": {
        "done": 2,
        "extra": 1,
        "missed": 1,
        "skipped": 2,
        "time_trained": 659,
    },
}


def _person(base: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return {**copy.deepcopy(base), **changes}


def _stats(*people: dict[str, Any]) -> dict[str, Any]:
    return {
        **copy.deepcopy(STATS_EMPTY),
        "counting_from": "2026-10-01",
        "people": [copy.deepcopy(person) for person in people],
    }


def _ids(name: str) -> list[str]:
    return [f"sensor.ha_fitness_{name}_{key}" for key in KEYS]


def _person_entries(
    entity_registry: er.EntityRegistry, entry: MockConfigEntry
) -> dict[str, str]:
    """Return the registry's person sensors of the entry: unique id → entity id."""
    return {
        registry_entry.unique_id: registry_entry.entity_id
        for registry_entry in er.async_entries_for_config_entry(
            entity_registry, entry.entry_id
        )
        if registry_entry.unique_id.startswith(f"{entry.entry_id}_person_")
    }


def _expected_entries(
    entry: MockConfigEntry, *people: tuple[int, str]
) -> dict[str, str]:
    return {
        f"{entry.entry_id}_person_{person_id}_{key}": f"sensor.ha_fitness_{name}_{key}"
        for person_id, name in people
        for key in KEYS
    }


def _states(hass: HomeAssistant, name: str) -> list[str | None]:
    return [
        None if (state := hass.states.get(entity_id)) is None else state.state
        for entity_id in _ids(name)
    ]


def _all_available(hass: HomeAssistant, name: str) -> bool:
    return all(
        state is not None and state != STATE_UNAVAILABLE
        for state in _states(hass, name)
    )


def _all_unavailable(hass: HomeAssistant, name: str) -> bool:
    return all(state == STATE_UNAVAILABLE for state in _states(hass, name))


def _all_gone(hass: HomeAssistant, name: str) -> bool:
    return all(state is None for state in _states(hass, name))


def _no_errors(caplog: pytest.LogCaptureFixture) -> bool:
    return not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.usefixtures("cards_bundle")
async def test_four_sensors_per_person_with_states_and_attributes(
    hass: HomeAssistant, fake_addon: FakeAddon, config_entry: MockConfigEntry
) -> None:
    """Each person has a streak, done, missed and time trained sensor, as spec §5.1's table."""
    fake_addon.stats = _stats(PERSON_STATS, BO_STATS)
    await set_up(hass, config_entry)
    await wait_for(
        hass, lambda: _all_available(hass, "anna") and _all_available(hass, "bo")
    )

    def _state(entity_id: str) -> tuple[str, dict[str, Any]]:
        state = hass.states.get(entity_id)
        assert state is not None
        return state.state, dict(state.attributes)

    streak, attributes = _state("sensor.ha_fitness_anna_streak")
    assert streak == "3"
    assert attributes["state_class"] == "measurement"
    # No unit: HA would show a translated unit in English on a Danish HA (ha-notes.md).
    assert "unit_of_measurement" not in attributes
    assert "device_class" not in attributes

    done, attributes = _state("sensor.ha_fitness_anna_done")
    assert done == "12"
    assert attributes["state_class"] == "total"
    assert (
        attributes["this_month"],
        attributes["extra"],
        attributes["extra_this_month"],
    ) == (4, 2, 1)

    missed, attributes = _state("sensor.ha_fitness_anna_missed")
    assert missed == "2"  # missed 1 plus skipped 1
    assert attributes["state_class"] == "total"
    assert (
        attributes["this_month"],
        attributes["skipped"],
        attributes["skipped_this_month"],
    ) == (1, 1, 1)

    time_trained, attributes = _state("sensor.ha_fitness_anna_time_trained")
    assert time_trained == "360"
    assert attributes["device_class"] == "duration"
    assert attributes["unit_of_measurement"] == "min"
    assert attributes["state_class"] == "total"
    assert attributes["this_month"] == 120  # 7230 s, rounded down

    assert _state("sensor.ha_fitness_bo_streak")[0] == "0"
    done, attributes = _state("sensor.ha_fitness_bo_done")
    assert done == "7"
    assert (
        attributes["this_month"],
        attributes["extra"],
        attributes["extra_this_month"],
    ) == (2, 3, 1)
    missed, attributes = _state("sensor.ha_fitness_bo_missed")
    assert missed == "5"  # missed 2 plus skipped 3
    assert (
        attributes["this_month"],
        attributes["skipped"],
        attributes["skipped_this_month"],
    ) == (3, 3, 2)
    time_trained, attributes = _state("sensor.ha_fitness_bo_time_trained")
    assert time_trained == "99"  # 5999 s, rounded down
    assert attributes["this_month"] == 10  # 659 s, rounded down

    # A pushed change reaches the states.
    changed = _person(PERSON_STATS, streak=4)
    await fake_addon.push({"type": "stats", "data": _stats(changed, BO_STATS)})
    await wait_for(hass, lambda: _state("sensor.ha_fitness_anna_streak")[0] == "4")
    await unload(hass, config_entry)


@pytest.mark.parametrize(
    ("language", "names", "attribute_names"),
    [
        (
            "en",
            [
                "HA Fitness Anna streak",
                "HA Fitness Anna done",
                "HA Fitness Anna missed",
                "HA Fitness Anna time trained",
            ],
            {
                "done": {
                    "this_month": "This month",
                    "extra": "Extra sessions",
                    "extra_this_month": "Extra sessions this month",
                },
                "missed": {
                    "this_month": "This month",
                    "skipped": "Skipped",
                    "skipped_this_month": "Skipped this month",
                },
                "time_trained": {"this_month": "This month"},
            },
        ),
        (
            "da",
            [
                "HA Fitness Anna i træk",
                "HA Fitness Anna gennemført",
                "HA Fitness Anna missede",
                "HA Fitness Anna træningstid",
            ],
            {
                "done": {
                    "this_month": "Denne måned",
                    "extra": "Ekstra træninger",
                    "extra_this_month": "Ekstra træninger denne måned",
                },
                "missed": {
                    "this_month": "Denne måned",
                    "skipped": "Sprunget over",
                    "skipped_this_month": "Sprunget over denne måned",
                },
                "time_trained": {"this_month": "Denne måned"},
            },
        ),
    ],
)
@pytest.mark.usefixtures("cards_bundle")
async def test_sensor_names_translated_with_person(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    language: str,
    names: list[str],
    attribute_names: dict[str, dict[str, str]],
) -> None:
    """The names carry the add-on person's name; the names and attribute names are translated."""
    hass.config.language = language
    fake_addon.stats = _stats(PERSON_STATS)
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: _all_available(hass, "anna"))

    friendly = [
        hass.states.get(entity_id).attributes["friendly_name"]  # type: ignore[union-attr]
        for entity_id in _ids("anna")
    ]
    assert friendly == names

    translations = await async_get_translations(hass, language, "entity", {DOMAIN})
    prefix = f"component.{DOMAIN}.entity.sensor"
    assert f"{prefix}.streak.unit_of_measurement" not in translations
    for key, attributes in attribute_names.items():
        state = hass.states.get(f"sensor.ha_fitness_anna_{key}")
        assert state is not None
        for attribute, name in attributes.items():
            assert attribute in state.attributes
            assert (
                translations[f"{prefix}.{key}.state_attributes.{attribute}.name"]
                == name
            )
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_entity_ids_and_unique_ids(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The entity ids come from the person entity, the unique ids from the add-on person's id.

    A rename in the add-on keeps the entity ids and the unique ids.
    """
    hass.config.language = "da"
    other = _person(BO_STATS, name="Elin Ø", person_entity_id="person.elin")
    fake_addon.stats = _stats(PERSON_STATS, other)
    await set_up(hass, config_entry)
    await wait_for(
        hass, lambda: _all_available(hass, "anna") and _all_available(hass, "elin")
    )

    expected = _expected_entries(config_entry, (1, "anna"), (2, "elin"))
    assert _person_entries(entity_registry, config_entry) == expected

    renamed = _person(PERSON_STATS, name="Annie", streak=5)
    await fake_addon.push({"type": "stats", "data": _stats(renamed, other)})
    await wait_for(
        hass,
        lambda: (
            (state := hass.states.get("sensor.ha_fitness_anna_streak")) is not None
            and state.state == "5"
        ),
    )
    assert _person_entries(entity_registry, config_entry) == expected
    assert _no_errors(caplog)
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_sensors_unavailable_until_stats(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The sensors are unavailable while the add-on is unreachable, and after a connect until stats come."""
    fake_addon.stats = _stats(PERSON_STATS)
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: _all_available(hass, "anna"))

    fake_addon.send_stats = False
    await fake_addon.close_ws()
    await wait_for(hass, lambda: _all_unavailable(hass, "anna"))

    # Back: today has come, the stats haven't yet.
    await wait_for(hass, lambda: is_open(hass), freezer, 1)
    assert fake_addon.connects == 2
    assert _all_unavailable(hass, "anna")

    await fake_addon.push({"type": "stats", "data": _stats(PERSON_STATS)})
    await wait_for(hass, lambda: _all_available(hass, "anna"))
    assert _states(hass, "anna") == ["3", "12", "2", "360"]

    # After a reload, the sensors stay registered and unavailable until the first stats.
    await unload(hass, config_entry)
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: is_open(hass))
    for _ in range(SETTLE_ROUNDS):
        await asyncio.sleep(0)
    assert _person_entries(entity_registry, config_entry) == _expected_entries(
        config_entry, (1, "anna")
    )
    assert _all_unavailable(hass, "anna")

    await fake_addon.push({"type": "stats", "data": _stats(PERSON_STATS)})
    await wait_for(hass, lambda: _all_available(hass, "anna"))
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_person_added_and_removed(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Sensors come and go with the people, and a person re-added keeps the entity ids."""
    fake_addon.stats = _stats(PERSON_STATS)
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: _all_available(hass, "anna"))
    assert _person_entries(entity_registry, config_entry) == _expected_entries(
        config_entry, (1, "anna")
    )

    # A person added later gets four entities.
    await fake_addon.push({"type": "stats", "data": _stats(PERSON_STATS, BO_STATS)})
    await wait_for(hass, lambda: _all_available(hass, "bo"))
    both = _expected_entries(config_entry, (1, "anna"), (2, "bo"))
    assert _person_entries(entity_registry, config_entry) == both

    # The same stats again change nothing.
    await fake_addon.push({"type": "stats", "data": _stats(PERSON_STATS, BO_STATS)})
    await fake_addon.push({"type": "stats", "data": _stats(PERSON_STATS, BO_STATS)})
    await wait_for(hass, lambda: _all_available(hass, "bo"))
    assert _person_entries(entity_registry, config_entry) == both

    # A removed person's four leave the registry and the state machine.
    await fake_addon.push({"type": "stats", "data": _stats(BO_STATS)})
    await wait_for(hass, lambda: _all_gone(hass, "anna"))
    assert _person_entries(entity_registry, config_entry) == _expected_entries(
        config_entry, (2, "bo")
    )

    # The same HA person re-added gets a new add-on id, and the same entity ids.
    anna_again = _person(PERSON_STATS, id=3)
    await fake_addon.push({"type": "stats", "data": _stats(BO_STATS, anna_again)})
    await wait_for(hass, lambda: _all_available(hass, "anna"))
    assert _person_entries(entity_registry, config_entry) == _expected_entries(
        config_entry, (2, "bo"), (3, "anna")
    )

    # Removed and re-added in one push: the entity ids stay, with no _2.
    anna_once_more = _person(PERSON_STATS, id=4)
    await fake_addon.push({"type": "stats", "data": _stats(BO_STATS, anna_once_more)})
    await wait_for(
        hass,
        lambda: (
            _person_entries(entity_registry, config_entry)
            == _expected_entries(config_entry, (2, "bo"), (4, "anna"))
        ),
    )
    await wait_for(hass, lambda: _all_available(hass, "anna"))
    assert _no_errors(caplog)
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_people_changed_across_a_reload(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """After a reload, the first stats remove the entries of people who are gone.

    A person re-added with a new add-on id while HA was down gets the same entity ids.
    """
    fake_addon.stats = _stats(PERSON_STATS, BO_STATS)
    await set_up(hass, config_entry)
    await wait_for(
        hass, lambda: _all_available(hass, "anna") and _all_available(hass, "bo")
    )
    await unload(hass, config_entry)

    # Bo is removed, and Anna re-added with a new id.
    anna_again = _person(PERSON_STATS, id=3)
    fake_addon.stats = _stats(anna_again)
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: _all_available(hass, "anna"))
    await wait_for(hass, lambda: _all_gone(hass, "bo"))
    assert _person_entries(entity_registry, config_entry) == _expected_entries(
        config_entry, (3, "anna")
    )
    assert _states(hass, "anna") == ["3", "12", "2", "360"]
    assert _no_errors(caplog)
    await unload(hass, config_entry)
