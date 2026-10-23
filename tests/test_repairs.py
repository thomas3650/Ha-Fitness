"""Tests for the connection to the add-on: the repair issues, the backoff, the logging and the reload."""

import asyncio
from collections.abc import Callable
from datetime import timedelta
import logging

from aiohttp import web
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_HASSIO, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.service_info.hassio import HassioServiceInfo
from homeassistant.util import dt as dt_util
import pytest
from pytest_aiohttp import AiohttpServer
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.ha_fitness.const import DOMAIN

from .fake_addon import FakeAddon

UNSUPPORTED = "unsupported_api_version"
TOO_OLD = "addon_too_old"
LOGGER_NAME = "custom_components.ha_fitness"
POLL_ROUNDS = 100_000


async def _wait_for(
    hass: HomeAssistant,
    condition: Callable[[], bool],
    freezer: FrozenDateTimeFactory | None = None,
    seconds: float = 0,
) -> None:
    """Wait until the condition holds; with a freezer, first move the clock on by the given seconds.

    The connection runs in a background task over a real socket, so the test polls. The freezer
    freezes the event loop's clock too, so the poll yields with `sleep(0)` and gives up after a
    number of rounds (about two seconds), not after a time. A retry timer may be armed just after
    the tick, so every round also fires the time changes of the same span after the frozen now.
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


def _has_issue(issue_registry: ir.IssueRegistry, issue_id: str) -> Callable[[], bool]:
    return lambda: issue_registry.async_get_issue(DOMAIN, issue_id) is not None


def _levels(caplog: pytest.LogCaptureFixture) -> list[int]:
    """Return the levels of the integration's records at WARNING and above (never their text)."""
    return [
        record.levelno
        for record in caplog.records
        if record.name.startswith(LOGGER_NAME) and record.levelno >= logging.WARNING
    ]


async def _set_up(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.usefixtures("cards_bundle")
async def test_api_version_3_raises_issue(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
) -> None:
    """An add-on that says API version 3 in its hello raises unsupported_api_version."""
    fake_addon.api_version = 3
    await _set_up(hass, config_entry)

    await _wait_for(hass, _has_issue(issue_registry, UNSUPPORTED))

    issue = issue_registry.async_get_issue(DOMAIN, UNSUPPORTED)
    assert issue is not None
    assert issue.translation_key == UNSUPPORTED
    assert issue.translation_placeholders == {"api_version": "3", "supported": "1"}
    assert issue.severity is ir.IssueSeverity.ERROR
    assert not issue.is_fixable
    assert issue_registry.async_get_issue(DOMAIN, TOO_OLD) is None
    assert config_entry.state is ConfigEntryState.LOADED
    await _unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_unknown_and_malformed_messages_are_ignored(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Unknown types and malformed messages leave the connection up: a later hello still counts."""
    await _set_up(hass, config_entry)
    await _wait_for(hass, lambda: fake_addon.connects == 1)

    await fake_addon.push({"type": "session", "data": {}})
    await fake_addon.push({"type": "hello", "api_version": "3"})
    await fake_addon.push({"type": "today", "data": None})
    await fake_addon.push({"type": "event", "event": "due"})
    await fake_addon.push({"no_type": True})
    await fake_addon.push({"type": "hello", "version": "0.3.0", "api_version": 3})

    await _wait_for(hass, _has_issue(issue_registry, UNSUPPORTED))
    assert fake_addon.connects == 1
    await _unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_old_addon_raises_addon_too_old(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
) -> None:
    """A rejected handshake, while health answers and /today gives 404, raises addon_too_old."""
    fake_addon.old_addon = True
    await _set_up(hass, config_entry)

    await _wait_for(hass, _has_issue(issue_registry, TOO_OLD))

    issue = issue_registry.async_get_issue(DOMAIN, TOO_OLD)
    assert issue is not None
    assert issue.translation_key == TOO_OLD
    assert issue.severity is ir.IssueSeverity.ERROR
    assert not issue.is_fixable
    assert issue_registry.async_get_issue(DOMAIN, UNSUPPORTED) is None
    assert config_entry.state is ConfigEntryState.LOADED
    await _unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_supported_connect_deletes_issues(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Both issues are raised in turn as the client retries, and a supported connect deletes both."""
    fake_addon.api_version = 3
    await _set_up(hass, config_entry)
    await _wait_for(hass, _has_issue(issue_registry, UNSUPPORTED))

    # The add-on restarts as an old one: the client retries after 1 s and is rejected.
    fake_addon.api_version = 1
    fake_addon.old_addon = True
    await fake_addon.close_ws()
    await _wait_for(hass, _has_issue(issue_registry, TOO_OLD), freezer, 1)
    assert issue_registry.async_get_issue(DOMAIN, UNSUPPORTED) is not None

    # The add-on is updated: the next retry, 2 s later, connects with API version 1.
    fake_addon.old_addon = False
    await _wait_for(
        hass,
        lambda: (
            issue_registry.async_get_issue(DOMAIN, UNSUPPORTED) is None
            and issue_registry.async_get_issue(DOMAIN, TOO_OLD) is None
        ),
        freezer,
        2,
    )
    assert fake_addon.connects == 2
    await _unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle", "socket_enabled")
async def test_setup_does_not_wait_for_addon(
    hass: HomeAssistant, unused_tcp_port: int, caplog: pytest.LogCaptureFixture
) -> None:
    """With nothing listening at the URL, the entry still loads, warns, and unloads cleanly."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HA Fitness",
        data={"url": f"http://127.0.0.1:{unused_tcp_port}"},
        unique_id="ha_fitness",
        version=2,
    )
    entry.add_to_hass(hass)

    await _set_up(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    await _wait_for(hass, lambda: bool(_levels(caplog)))
    assert _levels(caplog) == [logging.WARNING]
    await _unload(hass, entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_unreachable_addon_warns_once_per_outage(
    hass: HomeAssistant,
    socket_enabled: None,
    aiohttp_server: AiohttpServer,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An add-on that is down is retried after 1, 2, 5 and then 10 s; that is logged once, at WARNING, never ERROR."""
    attempts = 0
    health_checks = 0

    async def _down(request: web.Request) -> web.Response:
        nonlocal attempts, health_checks
        if request.path == "/api/v1/ws":
            attempts += 1
        if request.path == "/api/v1/health":
            health_checks += 1
        return web.Response(status=503)

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", _down)
    server = await aiohttp_server(app)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HA Fitness",
        data={"url": f"http://127.0.0.1:{server.port}"},
        unique_id="ha_fitness",
        version=2,
    )
    entry.add_to_hass(hass)

    await _set_up(hass, entry)

    async def _retry_is_pending(attempt: int, too_early: float) -> None:
        """Let the client arm its next retry, and check that it doesn't fire `too_early` seconds on."""
        await _wait_for(hass, lambda: health_checks == attempt)
        for _ in range(1000):
            await asyncio.sleep(0)
        for _ in range(1000):
            async_fire_time_changed(
                hass, dt_util.utcnow() + timedelta(seconds=too_early)
            )
            await asyncio.sleep(0)
        assert attempts == attempt

    await _wait_for(hass, lambda: attempts == 1)
    await _wait_for(hass, lambda: attempts == 2, freezer, 1)
    # async_fire_time_changed reaches 0.5 s past the time it is given.
    await _retry_is_pending(2, 1)
    await _wait_for(hass, lambda: attempts == 3, freezer, 2)
    await _retry_is_pending(3, 4)
    await _wait_for(hass, lambda: attempts == 4, freezer, 5)

    assert _levels(caplog) == [logging.WARNING]

    # Each rejected handshake is followed by a health check; once the fourth is answered, the
    # 10 s retry is pending. Unloaded, it never fires.
    await _retry_is_pending(4, 9)
    await _unload(hass, entry)
    for _ in range(1000):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=60))
        await asyncio.sleep(0)
    assert attempts == 4


@pytest.mark.usefixtures("cards_bundle")
async def test_discovery_reloads_entry_onto_new_url(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    aiohttp_server: AiohttpServer,
) -> None:
    """A discovery with a new address updates the loaded entry, which reloads and connects there."""
    await _set_up(hass, config_entry)
    await _wait_for(hass, lambda: fake_addon.connects == 1)

    moved = FakeAddon()
    server = await aiohttp_server(moved.app)
    moved.url = f"http://127.0.0.1:{server.port}"
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_HASSIO},
        data=HassioServiceInfo(
            config={"host": "127.0.0.1", "port": server.port},
            name="HA Fitness",
            slug="local_ha_fitness",
            uuid="1234",
        ),
    )
    await hass.async_block_till_done()

    assert result["reason"] == "already_configured"
    assert config_entry.data == {"url": moved.url}
    assert config_entry.state is ConfigEntryState.LOADED
    await _wait_for(hass, lambda: moved.connects == 1)
    await _wait_for(hass, lambda: not fake_addon.connected.is_set())
    await _unload(hass, config_entry)
