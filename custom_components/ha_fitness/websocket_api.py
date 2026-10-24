"""The cards' subscriptions: today (step 4 spec §4.5) and the session (the workout spec §4)."""

from datetime import datetime
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.components.websocket_api.decorators import websocket_command
from homeassistant.components.websocket_api.messages import event_message
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util
import probatio

from .const import DOMAIN, SIGNAL_UPDATE

_MISSING = object()


@callback
def async_setup_websocket_api(hass: HomeAssistant) -> None:
    """Register the websocket commands."""
    websocket_api.async_register_command(hass, ws_subscribe_today)
    websocket_api.async_register_command(hass, ws_subscribe_session)


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

    While the session runs past the countdown, time trained moves on by the same difference, so
    the card's elapsed time is right however long ago the add-on sent the view.
    """
    if view is None:
        return None
    now = dt_util.utcnow()
    fresh = {**view, "server_time": now.isoformat(timespec="milliseconds")}
    phase = view.get("phase")
    trained = view.get("time_trained")
    if (
        view.get("status") == "running"
        and isinstance(phase, dict)
        and phase.get("kind") != "countdown"
        and isinstance(trained, int | float)
        and (sent_at := _parse_time(view.get("server_time"))) is not None
    ):
        fresh["time_trained"] = round(trained + (now - sent_at).total_seconds(), 3)
    return fresh


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


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
