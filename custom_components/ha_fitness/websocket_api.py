"""The card's subscription, ha_fitness/today/subscribe (spec §4.5)."""

from typing import Any

from homeassistant.components import websocket_api
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.components.websocket_api.decorators import websocket_command
from homeassistant.components.websocket_api.messages import event_message
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
import probatio

from .const import DOMAIN, SIGNAL_UPDATE

_MISSING = object()


@callback
def async_setup_websocket_api(hass: HomeAssistant) -> None:
    """Register the websocket commands."""
    websocket_api.async_register_command(hass, ws_subscribe_today)


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
