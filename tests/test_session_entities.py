"""Tests for the session relay: the session-running sensor, the events and the session subscription."""

from datetime import datetime, timedelta
import logging
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)
from pytest_homeassistant_custom_component.typing import (
    MockHAClientWebSocket,
    WebSocketGenerator,
)

from custom_components.ha_fitness.const import DOMAIN

from .common import is_open, set_up, unload, wait_for
from .fake_addon import SESSION_RUNNING, FakeAddon

RUNNING = "binary_sensor.ha_fitness_session_running"
SUBSCRIBE = {"type": "ha_fitness/session/subscribe"}
TOO_OLD = "addon_too_old"


def _state(hass: HomeAssistant) -> str | None:
    state = hass.states.get(RUNNING)
    return None if state is None else state.state


def _freeze_on_whole_second(freezer: FrozenDateTimeFactory) -> datetime:
    """Freeze on the current whole second, so the milliseconds on the wire lose nothing.

    It stays near the real now: a jump of days would expire the websocket client's token.
    """
    freezer.move_to(dt_util.utcnow().replace(microsecond=0))
    return dt_util.utcnow()


def _iso(moment: datetime) -> str:
    """Write a UTC time as the add-on does: milliseconds and Z."""
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _view(**changes: Any) -> dict[str, Any]:
    """Return a copy of the running view, with the given fields changed."""
    return {**SESSION_RUNNING, **changes}


def _without_server_time(view: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in view.items() if key != "server_time"}


async def _subscribe(client: MockHAClientWebSocket) -> dict[str, Any]:
    """Subscribe; return the first message's event."""
    await client.send_json_auto_id(SUBSCRIBE)
    result = await client.receive_json()
    assert result["success"]
    first = await client.receive_json()
    assert first["id"] == result["id"]
    event: dict[str, Any] = first["event"]
    return event


async def _push_session(fake_addon: FakeAddon, view: dict[str, Any] | None) -> None:
    await fake_addon.push({"type": "session", "data": view})


@pytest.mark.usefixtures("cards_bundle")
async def test_sensor_unavailable_until_first_session_message_then_on_off(
    hass: HomeAssistant,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unavailable until the first session message; on while running or paused, else off."""
    fake_addon.send_session = False
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: is_open(hass))
    assert _state(hass) == STATE_UNAVAILABLE

    # Malformed session messages count as none; a later today proves they were read.
    await fake_addon.push({"type": "session"})
    await fake_addon.push({"type": "session", "data": 5})
    await fake_addon.push({"type": "today", "data": {**fake_addon.today, "open": []}})
    await wait_for(hass, lambda: not is_open(hass))
    assert _state(hass) == STATE_UNAVAILABLE
    # Nothing went wrong on the way: the guard dropped them, no listener choked on them.
    assert not [
        record
        for record in caplog.records
        if record.name.startswith("custom_components.ha_fitness")
        and record.levelno >= logging.WARNING
    ]

    await _push_session(fake_addon, _view())
    await wait_for(hass, lambda: _state(hass) == "on")
    state = hass.states.get(RUNNING)
    assert state is not None
    assert state.attributes["program"] == "Onsdag"
    assert state.attributes["participants"] == SESSION_RUNNING["participants"]

    await _push_session(fake_addon, _view(status="completed", revision=5))
    await wait_for(hass, lambda: _state(hass) == "off")

    await _push_session(fake_addon, _view(status="paused", revision=6))
    await wait_for(hass, lambda: _state(hass) == "on")

    await _push_session(fake_addon, None)
    await wait_for(hass, lambda: _state(hass) == "off")
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_sensor_unavailable_on_disconnect(
    hass: HomeAssistant, fake_addon: FakeAddon, config_entry: MockConfigEntry
) -> None:
    """A dropped connection makes the sensor unavailable, never off."""
    fake_addon.session = _view()
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: _state(hass) == "on")

    await fake_addon.close_ws()
    await wait_for(hass, lambda: _state(hass) == STATE_UNAVAILABLE)
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_events_fired_with_data(
    hass: HomeAssistant, fake_addon: FakeAddon, config_entry: MockConfigEntry
) -> None:
    """The session events and done become Home Assistant events, with the add-on's data."""
    names = (
        "session_started",
        "session_completed",
        "session_ended",
        "phase_changed",
    )
    captured = {
        name: async_capture_events(hass, f"{DOMAIN}_{name}")
        for name in (*names, "training_day_done")
    }
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: is_open(hass))

    sessions = {
        name: {"id": 7, "program_name": name, "training_day_id": 12} for name in names
    }
    sessions["session_ended"]["counted"] = True
    sessions["phase_changed"]["phase"] = {
        **SESSION_RUNNING["phase"],
        "index": 4,
        "kind": "switch",
        "duration": 15,
        "ends_at": "2026-10-28T17:00:55.000Z",
    }
    for name in names:
        await fake_addon.push(
            {"type": "event", "event": name, "session": sessions[name]}
        )
    day = {"id": 12, "program_id": 3, "program_name": "Onsdag", "date": "2026-10-28"}
    await fake_addon.push({"type": "event", "event": "done", "training_day": day})
    await wait_for(hass, lambda: len(captured["training_day_done"]) == 1)

    for name in names:
        assert [event.data for event in captured[name]] == [sessions[name]]
    assert captured["training_day_done"][0].data == day
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_subscription_fresh_server_time_and_time_trained(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Each send carries HA's now; a running view past the countdown advances time trained."""
    start = _freeze_on_whole_second(freezer)
    view = _view(server_time=_iso(start))
    fake_addon.session = view
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: _state(hass) == "on")
    client = await hass_ws_client(hass)

    first = await _subscribe(client)
    assert first["available"] is True
    assert _without_server_time(first["session"]) == _without_server_time(view)
    # The view keeps the add-on's time format: UTC with milliseconds and Z.
    assert first["session"]["server_time"] == _iso(start)

    freezer.tick(timedelta(seconds=30))
    second = await _subscribe(client)
    assert second["available"] is True
    session = second["session"]
    assert session["server_time"] == _iso(start + timedelta(seconds=30))
    assert session["time_trained"] == 130
    assert _without_server_time({**session, "time_trained": 100}) == (
        _without_server_time(view)
    )

    # Whole seconds, as the add-on sends: 130.6 s is 131.
    freezer.tick(timedelta(milliseconds=600))
    third = (await _subscribe(client))["session"]
    assert third["time_trained"] == 131
    assert isinstance(third["time_trained"], int)

    # A push that differs only in server_time sends nothing; the next real change is next.
    await _push_session(fake_addon, {**view, "server_time": _iso(dt_util.utcnow())})
    await _push_session(fake_addon, {**view, "revision": 5})
    for _ in range(2):
        assert (await client.receive_json())["event"]["session"]["revision"] == 5
    await unload(hass, config_entry)


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "paused"},
        {"phase": {**SESSION_RUNNING["phase"], "kind": "countdown"}},
        {"status": "completed"},
    ],
    ids=["paused", "countdown", "completed"],
)
@pytest.mark.usefixtures("cards_bundle")
async def test_subscription_keeps_time_trained_unless_running_past_countdown(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    changes: dict[str, Any],
) -> None:
    """Paused, in the countdown or finished, time trained is sent as the add-on gave it."""
    start = _freeze_on_whole_second(freezer)
    fake_addon.session = _view(server_time=_iso(start), **changes)
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: _state(hass) in ("on", "off"))
    client = await hass_ws_client(hass)

    freezer.tick(timedelta(seconds=30))
    session = (await _subscribe(client))["session"]
    assert dt_util.parse_datetime(session["server_time"]) == start + timedelta(
        seconds=30
    )
    assert session["time_trained"] == 100
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_subscription_unavailable_keeps_last_view(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """While the add-on is unreachable the subscription sends available false and the last view."""
    view = _view(server_time=_iso(_freeze_on_whole_second(freezer)))
    fake_addon.session = view
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: _state(hass) == "on")
    client = await hass_ws_client(hass)
    first = await _subscribe(client)
    assert first["available"] is True

    await fake_addon.close_ws()
    message = (await client.receive_json())["event"]
    assert message == {"available": False, "session": view}
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_subscription_without_loaded_entry(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
) -> None:
    """With no loaded entry the subscription sends available false and no session."""
    fake_addon.session = _view()
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: _state(hass) == "on")
    await unload(hass, config_entry)

    client = await hass_ws_client(hass)
    assert await _subscribe(client) == {"available": False, "session": None}


@pytest.mark.usefixtures("cards_bundle")
async def test_no_sessions_mode_raises_addon_too_old_after_hello(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
) -> None:
    """An add-on without sessions connects, but /session's 404 raises addon_too_old."""
    fake_addon.no_sessions = True
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: is_open(hass))
    await wait_for(
        hass, lambda: issue_registry.async_get_issue(DOMAIN, TOO_OLD) is not None
    )
    issue = issue_registry.async_get_issue(DOMAIN, TOO_OLD)
    assert issue is not None
    assert issue.translation_key == TOO_OLD
    assert _state(hass) == STATE_UNAVAILABLE

    client = await hass_ws_client(hass)
    assert await _subscribe(client) == {"available": False, "session": None}

    # Each hello deletes the issue; the probe after it raises it again.
    await fake_addon.push({"type": "hello", "version": "0.2.0", "api_version": 1})
    await wait_for(
        hass, lambda: issue_registry.async_get_issue(DOMAIN, TOO_OLD) is None
    )
    await wait_for(
        hass, lambda: issue_registry.async_get_issue(DOMAIN, TOO_OLD) is not None
    )
    await unload(hass, config_entry)
