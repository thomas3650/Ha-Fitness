"""Helpers shared by the HA Fitness tests."""

import asyncio
from collections.abc import Callable
from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

POLL_ROUNDS = 100_000
TRAINING_OPEN = "binary_sensor.ha_fitness_training_open"


def is_open(hass: HomeAssistant) -> bool:
    """Return whether the entities show the fake's open day: connected, with today received."""
    state = hass.states.get(TRAINING_OPEN)
    return state is not None and state.state == "on"


def is_unavailable(hass: HomeAssistant) -> bool:
    """Return whether the entities are unavailable."""
    state = hass.states.get(TRAINING_OPEN)
    return state is not None and state.state == "unavailable"


async def wait_for(
    hass: HomeAssistant,
    condition: Callable[[], bool],
    freezer: FrozenDateTimeFactory | None = None,
    seconds: float = 0,
) -> None:
    """Wait until the condition holds; with a freezer, first move the clock on by the given seconds.

    The connection runs in a background task over a real socket, so the test polls. Under the
    freezer the event loop's clock stands still between ticks, so the poll yields with `sleep(0)`
    and gives up after a number of rounds (about two seconds), not after a time. A retry timer may
    be armed just after the tick, so every round also fires the time changes of the same span
    after the frozen now. That fires aiohttp's own timers too, so keep `seconds` short: from about
    15 s on, a connect timeout or a pong timeout can fire before the socket answers.
    """
    if freezer is not None:
        freezer.tick(timedelta(seconds=seconds))
    for _ in range(POLL_ROUNDS):
        if condition():
            return
        if freezer is not None:
            async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
        await asyncio.sleep(0)
    pytest.fail("the condition did not come true")


async def set_up(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set the entry up and let setup finish (the connection keeps running in the background)."""
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Unload the entry, so no connection task or timer is left behind."""
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
