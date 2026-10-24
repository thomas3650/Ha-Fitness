"""Tests for the entities and the device, observed through entity states and the registries."""

import asyncio
import copy
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_fitness.const import DOMAIN

from .common import set_up, unload, wait_for
from .fake_addon import TODAY_DUE, FakeAddon

TODAY = "sensor.ha_fitness_today"
NEXT = "sensor.ha_fitness_next_training_day"
OPEN = "binary_sensor.ha_fitness_training_open"
RUNNING = "binary_sensor.ha_fitness_session_running"
ENTITY_IDS = (TODAY, NEXT, OPEN, RUNNING)

LATE_DAY: dict[str, Any] = {
    **TODAY_DUE["open"][0],
    "id": 13,
    "program_name": "Mandag",
    "date": "2026-10-26",
    "state": "late",
}


def _state(hass: HomeAssistant, entity_id: str) -> str | None:
    state = hass.states.get(entity_id)
    return None if state is None else state.state


def _is(hass: HomeAssistant, entity_id: str, value: str) -> bool:
    return _state(hass, entity_id) == value


async def _connected(hass: HomeAssistant) -> None:
    """Wait until the fake's first today has reached the entities."""
    await wait_for(hass, lambda: _is(hass, OPEN, "on"))


@pytest.mark.usefixtures("cards_bundle")
async def test_entity_ids_on_danish_ha(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """On a Danish HA the entity ids are still the English ones; the names are Danish."""
    hass.config.language = "da"
    await set_up(hass, config_entry)
    await _connected(hass)

    entry_id = config_entry.entry_id
    assert {
        entry.unique_id: entry.entity_id
        for entry in er.async_entries_for_config_entry(entity_registry, entry_id)
    } == {
        f"{entry_id}_today": TODAY,
        f"{entry_id}_next_training_day": NEXT,
        f"{entry_id}_training_open": OPEN,
        f"{entry_id}_session_running": RUNNING,
    }
    names = {
        entity_id: hass.states.get(entity_id).attributes["friendly_name"]  # type: ignore[union-attr]
        for entity_id in ENTITY_IDS
    }
    assert names == {
        TODAY: "HA Fitness Træning i dag",
        NEXT: "HA Fitness Næste træningsdag",
        OPEN: "HA Fitness Træning åben",
        RUNNING: "HA Fitness Træning i gang",
    }
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_states_and_attributes_from_today(
    hass: HomeAssistant, fake_addon: FakeAddon, config_entry: MockConfigEntry
) -> None:
    """The states and attributes follow each today message: due, then late, then nothing open."""
    await set_up(hass, config_entry)
    await _connected(hass)

    today = hass.states.get(TODAY)
    assert today is not None
    assert today.state == "due"
    assert today.attributes["training_days"] == TODAY_DUE["open"]
    assert today.attributes["options"] == ["none", "due", "late"]
    assert today.attributes["friendly_name"] == "HA Fitness Training today"
    next_day = hass.states.get(NEXT)
    assert next_day is not None
    assert next_day.state == "2026-10-31"
    assert next_day.attributes["programs"] == ["Lørdag"]
    assert next_day.attributes["friendly_name"] == "HA Fitness Next training day"
    training_open = hass.states.get(OPEN)
    assert training_open is not None
    assert training_open.state == "on"
    assert training_open.attributes["friendly_name"] == "HA Fitness Training open"

    late = {**copy.deepcopy(TODAY_DUE), "date": "2026-10-27", "open": [LATE_DAY]}
    await fake_addon.push({"type": "today", "data": late})
    await wait_for(hass, lambda: _is(hass, TODAY, "late"))
    assert hass.states.get(TODAY).attributes["training_days"] == [LATE_DAY]  # type: ignore[union-attr]
    assert _state(hass, OPEN) == "on"

    nothing: dict[str, Any] = {"date": "2026-10-28", "open": [], "next": None}
    await fake_addon.push({"type": "today", "data": nothing})
    await wait_for(hass, lambda: _is(hass, TODAY, "none"))
    assert hass.states.get(TODAY).attributes["training_days"] == []  # type: ignore[union-attr]
    assert _state(hass, NEXT) == STATE_UNKNOWN
    assert hass.states.get(NEXT).attributes["programs"] == []  # type: ignore[union-attr]
    assert _state(hass, OPEN) == "off"
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_unavailable_on_disconnect_and_back_on_reconnect(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """When the add-on restarts, every entity is unavailable, and back once it reconnects."""
    await set_up(hass, config_entry)
    await _connected(hass)

    await fake_addon.close_ws()
    await wait_for(
        hass, lambda: all(_is(hass, e, STATE_UNAVAILABLE) for e in ENTITY_IDS)
    )

    await wait_for(hass, lambda: _is(hass, OPEN, "on"), freezer, 1)
    assert fake_addon.connects == 2
    assert _state(hass, TODAY) == "due"
    assert _state(hass, NEXT) == "2026-10-31"
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_device_sw_version_from_hello(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The one device, HA Fitness, carries the add-on's version from hello, and follows an update."""

    def _sw_version() -> str | None:
        device = device_registry.async_get_device_by_identifier(
            (DOMAIN, config_entry.entry_id), config_entry.entry_id
        )
        return None if device is None else device.sw_version

    await set_up(hass, config_entry)
    await wait_for(hass, lambda: _sw_version() == "0.2.0")

    devices = dr.async_entries_for_config_entry(device_registry, config_entry.entry_id)
    assert [device.name for device in devices] == ["HA Fitness"]

    fake_addon.version = "0.2.1"
    await fake_addon.close_ws()
    await wait_for(hass, lambda: _sw_version() == "0.2.1", freezer, 1)
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_no_hello_keeps_entry_loaded_and_entities_unavailable(
    hass: HomeAssistant, fake_addon: FakeAddon, config_entry: MockConfigEntry
) -> None:
    """An add-on that accepts the ws but never says hello leaves the entry loaded, entities unavailable."""
    fake_addon.send_hello = False
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: fake_addon.connects == 1)

    assert config_entry.state is ConfigEntryState.LOADED
    assert all(_is(hass, e, STATE_UNAVAILABLE) for e in ENTITY_IDS)
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_unsupported_api_version_keeps_entities_unavailable(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
) -> None:
    """On an unsupported API version the entities stay unavailable, even as today messages arrive."""
    fake_addon.api_version = 3
    await set_up(hass, config_entry)
    await wait_for(
        hass,
        lambda: (
            issue_registry.async_get_issue(DOMAIN, "unsupported_api_version")
            is not None
        ),
    )
    # The fake sent today right after its hello; let the client read it.
    await fake_addon.push({"type": "today", "data": TODAY_DUE})
    for _ in range(1000):
        await asyncio.sleep(0)

    assert all(_is(hass, e, STATE_UNAVAILABLE) for e in ENTITY_IDS)
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_unsupported_hello_on_a_live_connection_makes_entities_unavailable(
    hass: HomeAssistant, fake_addon: FakeAddon, config_entry: MockConfigEntry
) -> None:
    """A later hello with an unsupported API version turns the entities unavailable."""
    await set_up(hass, config_entry)
    await _connected(hass)

    await fake_addon.push({"type": "hello", "version": "0.3.0", "api_version": 3})

    await wait_for(
        hass, lambda: all(_is(hass, e, STATE_UNAVAILABLE) for e in ENTITY_IDS)
    )
    await unload(hass, config_entry)
