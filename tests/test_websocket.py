"""Tests for the card's subscription, ha_fitness/today/subscribe."""

import copy

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from .common import is_open, set_up, unload, wait_for
from .fake_addon import TODAY_DUE, FakeAddon

SUBSCRIBE = {"type": "ha_fitness/today/subscribe"}


@pytest.mark.usefixtures("cards_bundle")
async def test_subscription_sends_data_and_null(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
) -> None:
    """The subscription sends today at once and after each change, and null on a disconnect."""
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: is_open(hass))
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(SUBSCRIBE)
    result = await client.receive_json()
    assert result["success"]
    first = await client.receive_json()
    assert first["type"] == "event"
    assert first["id"] == result["id"]
    assert first["event"] == TODAY_DUE

    changed = copy.deepcopy(TODAY_DUE)
    changed["open"] = []
    await fake_addon.push({"type": "today", "data": changed})
    assert (await client.receive_json())["event"] == changed

    await fake_addon.close_ws()
    assert (await client.receive_json())["event"] is None
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_subscription_sends_null_without_loaded_entry_then_data(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
) -> None:
    """Subscribed before the entry is set up, it sends null, then the data once the add-on connects."""
    await set_up(hass, config_entry)
    await unload(hass, config_entry)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(SUBSCRIBE)
    assert (await client.receive_json())["success"]
    assert (await client.receive_json())["event"] is None

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    assert (await client.receive_json())["event"] == TODAY_DUE

    await unload(hass, config_entry)
    assert (await client.receive_json())["event"] is None


@pytest.mark.usefixtures("cards_bundle")
async def test_subscription_passes_the_week_through(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
) -> None:
    """A week in the add-on's today reaches the card as it is."""
    week = [{"date": "2026-10-26", "programs": ["Onsdag"]}]
    fake_addon.today = {**copy.deepcopy(TODAY_DUE), "week": week}
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: is_open(hass))
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(SUBSCRIBE)
    assert (await client.receive_json())["success"]
    assert (await client.receive_json())["event"]["week"] == week
    await unload(hass, config_entry)
