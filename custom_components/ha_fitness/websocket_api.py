"""The cards' websocket commands (the workout spec §4).

The subscriptions to today (step 4 spec §4.5), to the session and to the stats (the stats spec
§5.1); the session command; the programs, people and speakers lists. None needs an admin: the tablet's user isn't one.
"""

import re
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.components.websocket_api.decorators import (
    async_response,
    websocket_command,
)
from homeassistant.components.websocket_api.messages import event_message
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util
import probatio

from .client import (
    AddonConnectionError,
    SessionRefusedError,
    async_people,
    async_programs,
    async_session_command,
    async_session_feeling,
    async_start_session,
)
from .const import DOMAIN, SIGNAL_UPDATE
from .coordinator import FitnessCoordinator, usable_coordinator
from .music import _parse_time, music_speakers

_MISSING = object()

# The add-on's pattern for `Music.speaker` (the music spec §5.5).
SPEAKER_PATTERN = re.compile(r"media_player\.[a-z0-9_]+")

SESSION_COMMANDS = (
    "start",
    "pause",
    "resume",
    "next",
    "previous",
    "end",
    "feeling",
)


@callback
def async_setup_websocket_api(hass: HomeAssistant) -> None:
    """Register the websocket commands."""
    websocket_api.async_register_command(hass, ws_subscribe_today)
    websocket_api.async_register_command(hass, ws_subscribe_session)
    websocket_api.async_register_command(hass, ws_subscribe_stats)
    websocket_api.async_register_command(hass, ws_session_command)
    websocket_api.async_register_command(hass, ws_programs)
    websocket_api.async_register_command(hass, ws_people)
    websocket_api.async_register_command(hass, ws_speakers)


def _current_today(hass: HomeAssistant) -> dict[str, Any] | None:
    """Return today from the loaded entry, or None while unloaded, disconnected or unsupported."""
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        coordinator = entry.runtime_data
        if coordinator.available:
            today: dict[str, Any] = coordinator.today
            return today
    return None


@websocket_command({probatio.Required("type"): "ha_fitness/today/subscribe"})
@callback
def ws_subscribe_today(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Send today at once and after each change; null while the add-on can't be used.

    It follows the dispatcher, not one coordinator, so it survives an entry reload.
    """
    last: object = _MISSING

    @callback
    def send() -> None:
        nonlocal last
        today = _current_today(hass)
        if today != last:
            last = today
            connection.send_message(event_message(msg["id"], today))

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(
        hass, SIGNAL_UPDATE, send
    )
    connection.send_result(msg["id"])
    send()


def _current_session(hass: HomeAssistant) -> tuple[bool, dict[str, Any] | None]:
    """Return whether the session can be used, and the add-on's last view (kept while unreachable)."""
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        coordinator = entry.runtime_data
        session: dict[str, Any] | None = coordinator.session
        return coordinator.session_available, session
    return False, None


def _without_server_time(view: dict[str, Any] | None) -> dict[str, Any] | None:
    if view is None:
        return None
    return {key: value for key, value in view.items() if key != "server_time"}


def _fresh(view: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a copy of the view with HA's now as server_time.

    While the session runs past the countdown, time trained moves on by the same difference, in
    whole seconds as the add-on sends it, so the card's elapsed time is right however long ago
    the add-on sent the view.
    """
    if view is None:
        return None
    now = dt_util.utcnow()
    # The add-on's format: UTC with milliseconds and Z.
    server_time = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    fresh = {**view, "server_time": server_time}
    phase = view.get("phase")
    trained = view.get("time_trained")
    if (
        view.get("status") == "running"
        and isinstance(phase, dict)
        and phase.get("kind") != "countdown"
        and isinstance(trained, int | float)
        and (sent_at := _parse_time(view.get("server_time"))) is not None
    ):
        fresh["time_trained"] = round(trained + (now - sent_at).total_seconds())
    return fresh


@websocket_command({probatio.Required("type"): "ha_fitness/session/subscribe"})
@callback
def ws_subscribe_session(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Send `{available, session}` at once and after each change, with a fresh server_time.

    A change is a change of the add-on's raw view, server_time left out, or of `available`. It
    follows the dispatcher, not one coordinator, so it survives an entry reload.
    """
    last: object = _MISSING

    @callback
    def send() -> None:
        nonlocal last
        available, session = _current_session(hass)
        key = (available, _without_server_time(session))
        if key != last:
            last = key
            connection.send_message(
                event_message(
                    msg["id"], {"available": available, "session": _fresh(session)}
                )
            )

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(
        hass, SIGNAL_UPDATE, send
    )
    connection.send_result(msg["id"])
    send()


def _current_stats(hass: HomeAssistant) -> tuple[bool, dict[str, Any] | None]:
    """Return whether the stats can be used, and the add-on's last stats (kept while unreachable)."""
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        coordinator = entry.runtime_data
        stats: dict[str, Any] | None = coordinator.stats
        return coordinator.stats_available, stats
    return False, None


@websocket_command({probatio.Required("type"): "ha_fitness/stats/subscribe"})
@callback
def ws_subscribe_stats(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Send `{available, stats}` at once and after each change of either.

    It follows the dispatcher, not one coordinator, so it survives an entry reload.
    """
    last: object = _MISSING

    @callback
    def send() -> None:
        nonlocal last
        available, stats = _current_stats(hass)
        key = (available, stats)
        if key != last:
            last = key
            connection.send_message(
                event_message(msg["id"], {"available": available, "stats": stats})
            )

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(
        hass, SIGNAL_UPDATE, send
    )
    connection.send_result(msg["id"])
    send()


def _send_error(connection: ActiveConnection, msg_id: int, code: str) -> None:
    """Send one of the codes not_found, conflict, invalid or unavailable, with its translation key."""
    key = "unavailable" if code == "unavailable" else f"session_{code}"
    connection.send_error(
        msg_id,
        code,
        f"HA Fitness: {code}",
        translation_key=key,
        translation_domain=DOMAIN,
    )


def _usable(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> FitnessCoordinator | None:
    """Return the usable coordinator, or send unavailable and return None."""
    coordinator = usable_coordinator(hass)
    if coordinator is None:
        _send_error(connection, msg["id"], "unavailable")
    return coordinator


@websocket_command(
    {
        probatio.Required("type"): "ha_fitness/session/command",
        probatio.Required("command"): probatio.In(SESSION_COMMANDS),
        probatio.Optional("program_id"): int,
        probatio.Optional("participants"): [int],
        probatio.Optional("training_day_id"): int,
        probatio.Optional("speaker"): str,
        probatio.Optional("feeling"): str,
    }
)
@async_response
async def ws_session_command(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Relay a command to the add-on and return the session view.

    `start` needs `program_id` and `participants`, and its optional `speaker` must match the add-on's pattern;
    `feeling` needs `feeling`; the add-on checks the rest. The speaker is passed on only while the add-on supports
    music (the music spec §5.6). A refusal keeps the add-on's code (not_found, conflict, invalid); anything else
    that fails is unavailable.
    """
    command: str = msg["command"]
    if command == "start" and (
        "program_id" not in msg
        or "participants" not in msg
        or ("speaker" in msg and not SPEAKER_PATTERN.fullmatch(msg["speaker"]))
    ):
        _send_error(connection, msg["id"], "invalid")
        return
    if command == "feeling" and "feeling" not in msg:
        _send_error(connection, msg["id"], "invalid")
        return
    if (coordinator := _usable(hass, connection, msg)) is None:
        return
    try:
        if command == "feeling":
            view = await async_session_feeling(
                coordinator.http_session,
                coordinator.url,
                msg["feeling"],
                coordinator.integration_version,
            )
        elif command == "start":
            view = await async_start_session(
                coordinator.http_session,
                coordinator.url,
                msg["program_id"],
                msg["participants"],
                msg.get("training_day_id"),
                coordinator.integration_version,
                msg.get("speaker") if coordinator.music_supported else None,
            )
        else:
            view = await async_session_command(
                coordinator.http_session,
                coordinator.url,
                command,
                coordinator.integration_version,
            )
    except SessionRefusedError as err:
        _send_error(connection, msg["id"], err.code)
        return
    except AddonConnectionError:
        _send_error(connection, msg["id"], "unavailable")
        return
    connection.send_result(msg["id"], view)


def _program(stored: dict[str, Any], music_supported: bool) -> dict[str, Any]:
    """Return one stored program (step 3's ProgramOut) in the shape of the workout spec §4.

    `music` is the add-on's, or null while the add-on doesn't support music (the music spec §5.5 and §5.6).
    """
    program = stored["program"]
    result: dict[str, Any] = {
        "id": stored["id"],
        "name": program["name"],
        "rounds": program["rounds"],
        "work_seconds": program["work_seconds"],
        "switch_seconds": program["switch_seconds"],
        "round_rest_seconds": program["round_rest_seconds"],
        "countdown_seconds": program["countdown_seconds"],
        # A half minute rounds up, as step 3's total_minutes does.
        "total_minutes": (stored["total_seconds"] + 30) // 60,
        "total_seconds": stored["total_seconds"],
        "stations": [
            {"exercise_id": station["exercise"], "name": name}
            for station, name in zip(
                program["stations"], stored["station_names"], strict=True
            )
        ],
        "music": program.get("music") if music_supported else None,
    }
    # An add-on from before equipment sends no list; the key stays out, so the cards hide "Du skal bruge".
    if "equipment" in stored:
        result["equipment"] = stored["equipment"]
    return result


@websocket_command({probatio.Required("type"): "ha_fitness/programs"})
@async_response
async def ws_programs(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the active programs, in the add-on's order (by name)."""
    if (coordinator := _usable(hass, connection, msg)) is None:
        return
    try:
        stored = await async_programs(coordinator.http_session, coordinator.url)
        # A malformed item (a missing key, stations and names that don't pair) is unavailable too.
        programs = [
            _program(item, coordinator.music_supported)
            for item in stored
            if item["program"]["active"]
        ]
    except AddonConnectionError, KeyError, TypeError, ValueError:
        _send_error(connection, msg["id"], "unavailable")
        return
    connection.send_result(msg["id"], programs)


@websocket_command({probatio.Required("type"): "ha_fitness/people"})
@async_response
async def ws_people(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the people, in the add-on's (colour) order, each `{id, name}`."""
    if (coordinator := _usable(hass, connection, msg)) is None:
        return
    try:
        stored = await async_people(coordinator.http_session, coordinator.url)
        # A malformed item (a missing key) is unavailable too.
        people = [{"id": person["id"], "name": person["name"]} for person in stored]
    except AddonConnectionError, KeyError, TypeError:
        _send_error(connection, msg["id"], "unavailable")
        return
    connection.send_result(msg["id"], people)


@websocket_command({probatio.Required("type"): "ha_fitness/speakers"})
@callback
def ws_speakers(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return Music Assistant's speakers, `{speakers: [{entity_id, name, available}]}`, sorted by name.

    It reads Home Assistant only, so it needs no add-on; without Music Assistant the list is empty.
    """
    connection.send_result(msg["id"], {"speakers": music_speakers(hass)})
