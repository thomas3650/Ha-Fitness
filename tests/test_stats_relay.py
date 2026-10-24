"""Tests for the stats relay: the stats message, the probe and the stats subscription (stats spec §5.1)."""

import asyncio
import copy
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import (
    MockHAClientWebSocket,
    WebSocketGenerator,
)

from custom_components.ha_fitness.const import DOMAIN

from .common import is_open, set_up, unload, wait_for
from .fake_addon import PERSON_STATS, STATS_EMPTY, FakeAddon

SUBSCRIBE = {"type": "ha_fitness/stats/subscribe"}
TOO_OLD = "addon_too_old"
# Settle rounds after the probe's request, to let its answer come back.
SETTLE_ROUNDS = 1000


def _stats_with_person() -> dict[str, Any]:
    return {**copy.deepcopy(STATS_EMPTY), "people": [copy.deepcopy(PERSON_STATS)]}


async def _subscribe(client: MockHAClientWebSocket) -> dict[str, Any]:
    """Subscribe; return the first message's event."""
    await client.send_json_auto_id(SUBSCRIBE)
    result = await client.receive_json()
    assert result["success"]
    first = await client.receive_json()
    assert first["id"] == result["id"]
    event: dict[str, Any] = first["event"]
    return event


async def _next_event(client: MockHAClientWebSocket) -> dict[str, Any]:
    event: dict[str, Any] = (await client.receive_json())["event"]
    return event


async def _subscribe_when_available(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> MockHAClientWebSocket:
    """Wait for the fake's stats on connect, then subscribe and check the first message."""
    await wait_for(hass, lambda: is_open(hass))
    client = await hass_ws_client(hass)
    first = await _subscribe(client)
    while not first["available"]:
        first = await _next_event(client)
    return client


@pytest.mark.usefixtures("cards_bundle")
async def test_stats_subscribe_first_message_and_change(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
) -> None:
    """The first message holds the stats sent on connect; a pushed change sends the new stats."""
    fake_addon.stats = _stats_with_person()
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: is_open(hass))
    client = await hass_ws_client(hass)
    first = await _subscribe(client)
    while not first["available"]:
        first = await _next_event(client)
    assert first == {"available": True, "stats": _stats_with_person()}

    changed = _stats_with_person()
    changed["people"][0]["streak"] = 4
    changed["people"][0]["all_time"]["done"] = 13
    await fake_addon.push({"type": "stats", "data": changed})
    assert await _next_event(client) == {"available": True, "stats": changed}

    # The same stats again send nothing; the next change is the next message.
    await fake_addon.push({"type": "stats", "data": changed})
    await fake_addon.push({"type": "stats", "data": STATS_EMPTY})
    assert await _next_event(client) == {"available": True, "stats": STATS_EMPTY}
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_stats_unavailable_between_connect_and_first_stats(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
) -> None:
    """After hello and before the first valid stats message, stats are unavailable."""
    fake_addon.send_stats = False
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: is_open(hass))
    client = await hass_ws_client(hass)
    assert await _subscribe(client) == {"available": False, "stats": None}

    # Malformed stats messages are ignored; the valid one after them is the next message.
    await fake_addon.push({"type": "stats", "data": None})
    await fake_addon.push({"type": "stats"})
    await fake_addon.push({"type": "stats", "data": _stats_with_person()})
    assert await _next_event(client) == {
        "available": True,
        "stats": _stats_with_person(),
    }

    # A new hello starts over: unavailable, with the last stats, until the next stats message.
    await fake_addon.push({"type": "hello", "version": "0.3.0", "api_version": 1})
    assert await _next_event(client) == {
        "available": False,
        "stats": _stats_with_person(),
    }
    await fake_addon.push({"type": "stats", "data": STATS_EMPTY})
    assert await _next_event(client) == {"available": True, "stats": STATS_EMPTY}
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_stats_unavailable_keeps_last(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
) -> None:
    """When the add-on closes, the subscription sends available false and the last stats."""
    fake_addon.stats = _stats_with_person()
    await set_up(hass, config_entry)
    client = await _subscribe_when_available(hass, hass_ws_client)

    await fake_addon.close_ws()
    assert await _next_event(client) == {
        "available": False,
        "stats": _stats_with_person(),
    }
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_stats_subscribe_without_loaded_entry(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
) -> None:
    """With no loaded entry the subscription sends available false and no stats."""
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: is_open(hass))
    await unload(hass, config_entry)

    client = await hass_ws_client(hass)
    assert await _subscribe(client) == {"available": False, "stats": None}


@pytest.mark.usefixtures("cards_bundle")
async def test_older_addon_raises_addon_too_old_for_stats(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
) -> None:
    """/stats answering 404 while health answers raises addon_too_old; a new add-on's hello deletes it."""
    fake_addon.no_stats = True
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: is_open(hass))
    await wait_for(
        hass, lambda: issue_registry.async_get_issue(DOMAIN, TOO_OLD) is not None
    )
    issue = issue_registry.async_get_issue(DOMAIN, TOO_OLD)
    assert issue is not None
    assert issue.translation_key == TOO_OLD
    assert issue.severity is ir.IssueSeverity.ERROR
    assert not issue.is_fixable

    client = await hass_ws_client(hass)
    assert await _subscribe(client) == {"available": False, "stats": None}

    # The add-on is updated: its hello deletes the issue, and the probe after it finds /stats.
    fake_addon.no_stats = False
    requests = fake_addon.stats_requests
    await fake_addon.push({"type": "hello", "version": "0.3.0", "api_version": 1})
    await wait_for(
        hass, lambda: issue_registry.async_get_issue(DOMAIN, TOO_OLD) is None
    )
    await wait_for(hass, lambda: fake_addon.stats_requests > requests)
    for _ in range(SETTLE_ROUNDS):
        await asyncio.sleep(0)
    assert issue_registry.async_get_issue(DOMAIN, TOO_OLD) is None

    await fake_addon.push({"type": "stats", "data": STATS_EMPTY})
    assert await _next_event(client) == {"available": True, "stats": STATS_EMPTY}
    await unload(hass, config_entry)
