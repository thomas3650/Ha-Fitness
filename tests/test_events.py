"""Tests for the events: one Home Assistant event per training-day event of the add-on."""

from typing import Any

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from .common import is_open, set_up, unload, wait_for
from .fake_addon import FakeAddon

DAY: dict[str, Any] = {
    "id": 12,
    "program_id": 3,
    "program_name": "Onsdag",
    "date": "2026-10-28",
}


@pytest.mark.usefixtures("cards_bundle")
async def test_events_fired_with_data(
    hass: HomeAssistant, fake_addon: FakeAddon, config_entry: MockConfigEntry
) -> None:
    """Due, skipped and missed become ha_fitness_training_day_<event>, with the day as data."""
    captured = {
        name: async_capture_events(hass, f"ha_fitness_training_day_{name}")
        for name in ("due", "skipped", "missed", "done")
    }
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: is_open(hass))

    # An event name this version doesn't know (done arrives in step 5) fires nothing.
    await fake_addon.push({"type": "event", "event": "done", "training_day": DAY})
    for name in ("due", "skipped", "missed"):
        day = {**DAY, "program_name": name}
        await fake_addon.push({"type": "event", "event": name, "training_day": day})
    await wait_for(hass, lambda: len(captured["missed"]) == 1)

    for name in ("due", "skipped", "missed"):
        assert [event.data for event in captured[name]] == [
            {**DAY, "program_name": name}
        ]
    assert captured["done"] == []
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_no_events_on_unsupported_api_version(
    hass: HomeAssistant, fake_addon: FakeAddon, config_entry: MockConfigEntry
) -> None:
    """While the add-on speaks an unsupported API version, its events fire nothing."""
    due = async_capture_events(hass, "ha_fitness_training_day_due")
    fake_addon.api_version = 3
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: fake_addon.connects == 1)

    await fake_addon.push({"type": "event", "event": "due", "training_day": DAY})
    # A supported hello afterwards proves the event was read before it.
    await fake_addon.push({"type": "hello", "version": "0.2.0", "api_version": 1})
    await fake_addon.push({"type": "event", "event": "due", "training_day": DAY})
    await wait_for(hass, lambda: len(due) == 1)
    await unload(hass, config_entry)
