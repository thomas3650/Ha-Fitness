"""Tests for the connection to the add-on: the repair issues, the backoff, the logging and the reload."""

import asyncio
from collections.abc import Callable
from datetime import timedelta
import logging
from typing import Any
from unittest.mock import patch

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
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.ha_fitness import client
from custom_components.ha_fitness.const import DOMAIN

from .common import is_open, is_unavailable, set_up, unload, wait_for
from .fake_addon import PROGRAMS, FakeAddon

UNSUPPORTED = "unsupported_api_version"
TOO_OLD = "addon_too_old"
LOGGER_NAME = "custom_components.ha_fitness"
NEXT_TRAINING_DAY = "sensor.ha_fitness_next_training_day"
# Event-loop rounds to let a background probe finish before checking that nothing changed.
SETTLE_ROUNDS = 1000


def _has_issue(issue_registry: ir.IssueRegistry, issue_id: str) -> Callable[[], bool]:
    return lambda: issue_registry.async_get_issue(DOMAIN, issue_id) is not None


def _levels(caplog: pytest.LogCaptureFixture) -> list[int]:
    """Return the levels of the integration's records at WARNING and above (never their text)."""
    return [
        record.levelno
        for record in caplog.records
        if record.name.startswith(LOGGER_NAME) and record.levelno >= logging.WARNING
    ]


@pytest.mark.usefixtures("cards_bundle")
async def test_api_version_3_raises_issue(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
) -> None:
    """An add-on that says API version 3 in its hello raises unsupported_api_version."""
    fake_addon.api_version = 3
    await set_up(hass, config_entry)

    await wait_for(hass, _has_issue(issue_registry, UNSUPPORTED))

    issue = issue_registry.async_get_issue(DOMAIN, UNSUPPORTED)
    assert issue is not None
    assert issue.translation_key == UNSUPPORTED
    assert issue.translation_placeholders == {"api_version": "3", "supported": "1"}
    assert issue.severity is ir.IssueSeverity.ERROR
    assert not issue.is_fixable
    assert issue_registry.async_get_issue(DOMAIN, TOO_OLD) is None
    assert config_entry.state is ConfigEntryState.LOADED
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_unknown_and_malformed_messages_are_ignored(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Unknown types and malformed messages leave the connection up: a later hello still counts."""
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: fake_addon.connects == 1)

    await fake_addon.push({"type": "unknown", "data": {}})
    await fake_addon.push({"type": "session"})
    await fake_addon.push({"type": "session", "data": 5})
    await fake_addon.push({"type": "event", "event": "phase_changed", "session": 5})
    await fake_addon.push({"type": "event", "session": {}})
    await fake_addon.push({"type": "hello", "api_version": "3"})
    await fake_addon.push({"type": "today", "data": None})
    await fake_addon.push({"type": "event", "event": "due"})
    await fake_addon.push({"no_type": True})
    await fake_addon.push({"type": "hello", "version": "0.3.0", "api_version": 3})

    await wait_for(hass, _has_issue(issue_registry, UNSUPPORTED))
    assert fake_addon.connects == 1
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_old_addon_raises_addon_too_old(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
) -> None:
    """A rejected handshake, while health answers and /today gives 404, raises addon_too_old."""
    fake_addon.old_addon = True
    await set_up(hass, config_entry)

    await wait_for(hass, _has_issue(issue_registry, TOO_OLD))

    issue = issue_registry.async_get_issue(DOMAIN, TOO_OLD)
    assert issue is not None
    assert issue.translation_key == TOO_OLD
    assert issue.severity is ir.IssueSeverity.ERROR
    assert not issue.is_fixable
    assert issue_registry.async_get_issue(DOMAIN, UNSUPPORTED) is None
    assert config_entry.state is ConfigEntryState.LOADED
    await unload(hass, config_entry)


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
    await set_up(hass, config_entry)
    await wait_for(hass, _has_issue(issue_registry, UNSUPPORTED))

    # The add-on restarts as an old one: the client retries after 1 s and is rejected.
    fake_addon.api_version = 1
    fake_addon.old_addon = True
    await fake_addon.close_ws()
    await wait_for(hass, _has_issue(issue_registry, TOO_OLD), freezer, 1)
    assert issue_registry.async_get_issue(DOMAIN, UNSUPPORTED) is not None

    # The add-on is updated: the next retry, 2 s later, connects with API version 1.
    fake_addon.old_addon = False
    await wait_for(
        hass,
        lambda: (
            issue_registry.async_get_issue(DOMAIN, UNSUPPORTED) is None
            and issue_registry.async_get_issue(DOMAIN, TOO_OLD) is None
        ),
        freezer,
        2,
    )
    assert fake_addon.connects == 2
    await unload(hass, config_entry)


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

    await set_up(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    await wait_for(hass, lambda: bool(_levels(caplog)))
    assert _levels(caplog) == [logging.WARNING]
    await unload(hass, entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_unreachable_addon_warns_once_per_outage(
    hass: HomeAssistant,
    socket_enabled: None,
    aiohttp_server: AiohttpServer,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An add-on that is down is retried after 1, 2, 5, 10 and then every 30 s; logged once, at WARNING, never ERROR."""
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

    await set_up(hass, entry)

    async def _retry_is_pending(attempt: int, too_early: float) -> None:
        """Let the client arm its next retry, and check that it doesn't fire `too_early` seconds on."""
        await wait_for(hass, lambda: health_checks == attempt)
        for _ in range(1000):
            await asyncio.sleep(0)
        for _ in range(1000):
            async_fire_time_changed(
                hass, dt_util.utcnow() + timedelta(seconds=too_early)
            )
            await asyncio.sleep(0)
        assert attempts == attempt

    await wait_for(hass, lambda: attempts == 1)
    await wait_for(hass, lambda: attempts == 2, freezer, 1)
    # async_fire_time_changed reaches 0.5 s past the time it is given.
    await _retry_is_pending(2, 1)
    await wait_for(hass, lambda: attempts == 3, freezer, 2)
    await _retry_is_pending(3, 4)
    await wait_for(hass, lambda: attempts == 4, freezer, 5)

    assert _levels(caplog) == [logging.WARNING]

    # Each rejected handshake is followed by a health check; once the fourth is answered, the
    # 10 s retry is pending. After it, the client retries every 30 s.
    await _retry_is_pending(4, 9)
    await wait_for(hass, lambda: attempts == 5, freezer, 10)

    async def _fire_pending_retry(seconds: float) -> None:
        """Fire the pending retry once: firing 30 s ahead on every poll would also fire aiohttp's connect timeout."""
        freezer.tick(timedelta(seconds=seconds))
        async_fire_time_changed(hass, dt_util.utcnow())

    for attempt in (6, 7):
        await _retry_is_pending(attempt - 1, 29)
        await _fire_pending_retry(30)
        await wait_for(hass, lambda: attempts == attempt)  # noqa: B023

    assert _levels(caplog) == [logging.WARNING]

    # Unloaded, the pending retry never fires.
    await _retry_is_pending(7, 29)
    await unload(hass, entry)
    for _ in range(1000):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=60))
        await asyncio.sleep(0)
    assert attempts == 7


@pytest.mark.usefixtures("cards_bundle")
async def test_discovery_reloads_entry_onto_new_url(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    aiohttp_server: AiohttpServer,
) -> None:
    """A discovery with a new address updates the loaded entry, which reloads and connects there."""
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: fake_addon.connects == 1)

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
    await wait_for(hass, lambda: moved.connects == 1)
    await wait_for(hass, lambda: not fake_addon.connected.is_set())
    await unload(hass, config_entry)


async def _settle() -> None:
    """Give the background connection a fair chance to act, where no signal says it is done."""
    for _ in range(1000):
        await asyncio.sleep(0)


def _next_training_day(hass: HomeAssistant) -> str | None:
    state = hass.states.get(NEXT_TRAINING_DAY)
    return None if state is None else state.state


@pytest.mark.usefixtures("cards_bundle")
async def test_failing_entity_update_does_not_block_others_or_reconnect(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A malformed today makes one entity's state write raise; the others still update, and the client reconnects."""
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: is_open(hass))

    # "open" isn't a list, so the today sensor raises while writing its state.
    malformed = {
        **fake_addon.today,
        "open": "x",
        "next": {"date": "2026-11-04", "programs": []},
    }
    await fake_addon.push({"type": "today", "data": malformed})
    await wait_for(hass, lambda: _next_training_day(hass) == "2026-11-04")
    assert fake_addon.connects == 1

    await fake_addon.close_ws()
    await wait_for(hass, lambda: fake_addon.connects == 2, freezer, 1)
    await wait_for(hass, lambda: _next_training_day(hass) == "2026-10-31")
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_handshake_without_hello_ends_the_outage(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A ws that opens, even without a hello, ends an outage: the next outage warns again."""
    fake_addon.old_addon = True
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: _levels(caplog) == [logging.WARNING])

    fake_addon.old_addon = False
    fake_addon.send_hello = False
    await wait_for(hass, lambda: fake_addon.connects == 1, freezer, 1)

    fake_addon.old_addon = True
    await fake_addon.close_ws()
    await wait_for(
        hass, lambda: _levels(caplog) == [logging.WARNING, logging.WARNING], freezer, 2
    )
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_heartbeat_keeps_a_live_connection(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Minutes pass on a live connection: each 31 s tick sends a ping, the pong comes, and it stays up."""
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: is_open(hass))

    for _ in range(10):
        freezer.tick(timedelta(seconds=31))
        async_fire_time_changed(hass, dt_util.utcnow())
        await _settle()

    assert fake_addon.connects == 1
    assert is_open(hass)
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_heartbeat_notices_a_half_open_connection(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A connection whose pings go unanswered is dropped: the entities turn unavailable."""
    fake_addon.answer_pings = False
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: is_open(hass))
    # Let aiohttp re-arm its heartbeat after the last message it read.
    await _settle()

    # After 30 s the ping goes out; the fake doesn't answer it.
    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(hass, dt_util.utcnow())
    await _settle()
    assert is_open(hass)

    # The pong was due 15 s after the ping.
    freezer.tick(timedelta(seconds=16))
    async_fire_time_changed(hass, dt_util.utcnow())
    await wait_for(hass, lambda: is_unavailable(hass))
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
# The client closes this ws itself; aiohttp 3.14 then re-arms its heartbeat timer as the add-on's
# close frame arrives, so one 30 s timer outlives the closed socket.
@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_unexpected_error_does_not_stop_reconnect(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A bug while reading a message drops the connection, warns, and the client reconnects."""
    real_parse = client.parse_message
    calls = 0

    def _parse_fails_once(raw: object) -> client.Message | None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("bug")
        return real_parse(raw)

    # White-box fault injection: no public input makes the client's own code raise here.
    monkeypatch.setattr(client, "parse_message", _parse_fails_once)
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: _levels(caplog) == [logging.WARNING])

    await wait_for(hass, lambda: is_open(hass), freezer, 1)
    assert fake_addon.connects == 2
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_failed_unload_keeps_the_connection(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """When the platforms fail to unload, the entry stays up: the client still reconnects."""
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: is_open(hass))

    with patch.object(
        hass.config_entries, "async_unload_platforms", return_value=False
    ):
        assert not await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.FAILED_UNLOAD

    await fake_addon.close_ws()
    await wait_for(hass, lambda: fake_addon.connects == 2, freezer, 1)
    await wait_for(hass, lambda: is_open(hass))

    # Clean up by hand: the entry can't be unloaded from FAILED_UNLOAD.
    config_entry.runtime_data.async_stop()
    await fake_addon.close_ws()
    await wait_for(hass, lambda: not fake_addon.connected.is_set())
    await hass.async_block_till_done()


async def _programs(hass_ws_client: WebSocketGenerator, hass: HomeAssistant) -> Any:
    """Return the result of ha_fitness/programs."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "ha_fitness/programs"})
    reply = await client.receive_json()
    assert reply["success"]
    return reply["result"]


@pytest.mark.usefixtures("cards_bundle")
async def test_probe_sets_music_supported(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Each probe sets music_supported from /music's answer; a disconnect keeps it."""
    fake_addon.no_music = True
    await set_up(hass, config_entry)
    # The issue is raised only after /music answered 404, so the probe has run.
    await wait_for(hass, _has_issue(issue_registry, TOO_OLD))
    coordinator = config_entry.runtime_data
    assert not coordinator.music_supported
    assert all(
        program["music"] is None for program in await _programs(hass_ws_client, hass)
    )

    # The add-on is updated: the probe after its hello finds /music.
    fake_addon.no_music = False
    await fake_addon.push({"type": "hello", "version": "0.3.0", "api_version": 1})
    await wait_for(hass, lambda: coordinator.music_supported)
    programs = await _programs(hass_ws_client, hass)
    assert programs[0]["music"] == PROGRAMS[1]["program"]["music"]

    # A disconnect keeps the flag, so a reconnect leaves no gap.
    await fake_addon.close_ws()
    await wait_for(hass, lambda: is_unavailable(hass))
    assert coordinator.music_supported
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_probe_404_on_music_raises_addon_too_old(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
) -> None:
    """/music answering 404 while health answers raises addon_too_old; a new add-on's hello deletes it."""
    fake_addon.no_music = True
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: is_open(hass))
    await wait_for(hass, _has_issue(issue_registry, TOO_OLD))
    issue = issue_registry.async_get_issue(DOMAIN, TOO_OLD)
    assert issue is not None
    assert issue.translation_key == TOO_OLD

    fake_addon.no_music = False
    requests = fake_addon.music_requests
    await fake_addon.push({"type": "hello", "version": "0.3.0", "api_version": 1})
    await wait_for(hass, lambda: fake_addon.music_requests > requests)
    for _ in range(SETTLE_ROUNDS):
        await asyncio.sleep(0)
    assert issue_registry.async_get_issue(DOMAIN, TOO_OLD) is None
    await unload(hass, config_entry)
