"""Hold the connection to the add-on and what it last pushed (spec §4.2)."""

from collections.abc import Callable
from datetime import datetime
import logging
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HassJob, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later

from .client import (
    AddonConnectionError,
    AddonHandshakeRejectedError,
    Hello,
    Message,
    Session,
    SessionEvent,
    StatsMessage,
    Today,
    async_health,
    async_listen,
    async_session_missing,
    async_stats_missing,
    async_today_missing,
)
from .const import (
    DOMAIN,
    EVENT_PREFIX,
    SESSION_EVENTS,
    SIGNAL_UPDATE,
    TRAINING_DAY_EVENTS,
)

_LOGGER = logging.getLogger(__name__)

# The add-on's API versions this integration speaks (docs/architecture.md).
SUPPORTED_API_VERSIONS = (1,)
# Seconds to wait before each reconnect; after the last one, every 30 s.
RECONNECT_DELAYS = (1, 2, 5, 10, 30)

ISSUE_UNSUPPORTED_API_VERSION = "unsupported_api_version"
ISSUE_ADDON_TOO_OLD = "addon_too_old"

UNREACHABLE = "The HA Fitness add-on at %s can't be reached; retrying"


class FitnessCoordinator:
    """Keep the push channel to the add-on open, and tell listeners when what it holds changes.

    `connected` is true while a supported add-on is connected. `today` is the add-on's last
    `today` message, and None while not connected. `session` is the add-on's last session view;
    it is kept across a disconnect, so the card can go on counting down. `session_seen` is true
    once a session message has come since the last connect. `stats` and `stats_seen` work the
    same way for the add-on's stats (the stats spec §5.1). Each change is also sent on the
    dispatcher (`SIGNAL_UPDATE`), which the cards' subscriptions follow across entry reloads.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry[Any],
        session: aiohttp.ClientSession,
        url: str,
        integration_version: str,
    ) -> None:
        """Set up the coordinator; `async_start` connects."""
        self.hass = hass
        self.entry = entry
        self.http_session = session
        self.url = url
        self.integration_version = integration_version
        self.connected = False
        self.today: dict[str, Any] | None = None
        self.session: dict[str, Any] | None = None
        self.session_seen = False
        self.stats: dict[str, Any] | None = None
        self.stats_seen = False
        self.addon_version: str | None = None
        self._listeners: list[CALLBACK_TYPE] = []
        self._attempt = 0
        self._outage_logged = False
        self._cancel_retry: CALLBACK_TYPE | None = None
        self._stopped = False

    @callback
    def async_add_listener(self, update_callback: CALLBACK_TYPE) -> Callable[[], None]:
        """Call `update_callback` on every change; return a function that removes it."""
        self._listeners.append(update_callback)

        def remove() -> None:
            self._listeners.remove(update_callback)

        return remove

    @callback
    def async_start(self) -> None:
        """Connect in the background; setup doesn't wait for the add-on."""
        self.entry.async_create_background_task(
            self.hass, self._async_connect(), f"{DOMAIN} push channel"
        )

    @callback
    def async_stop(self) -> None:
        """Stop reconnecting; the entry cancels the connection task on unload."""
        self._stopped = True
        if self._cancel_retry is not None:
            self._cancel_retry()
            self._cancel_retry = None

    @property
    def available(self) -> bool:
        """Return whether a supported add-on is connected and has sent what it holds."""
        return self.connected and self.today is not None

    @property
    def session_available(self) -> bool:
        """Return whether a supported add-on is connected and has sent its session."""
        return self.connected and self.session_seen

    @property
    def stats_available(self) -> bool:
        """Return whether a supported add-on is connected and has sent its stats."""
        return self.connected and self.stats_seen

    async def _async_connect(self) -> None:
        """Hold one connection until it ends, then schedule the next attempt."""
        try:
            await async_listen(
                self.http_session, self.url, self._handle_connect, self._handle_message
            )
        except AddonHandshakeRejectedError:
            if await self._async_check_too_old():
                self._log_outage("The HA Fitness add-on at %s is too old; retrying")
            else:
                self._log_outage(UNREACHABLE)
        except AddonConnectionError:
            self._log_outage(UNREACHABLE)
        except Exception:
            # A bug in a message handler or a listener must not end the reconnect loop.
            # CancelledError isn't an Exception, so unload still cancels the task.
            _LOGGER.warning(
                "Unexpected error on the HA Fitness push channel; reconnecting",
                exc_info=True,
            )
        else:
            _LOGGER.info("The HA Fitness add-on closed the connection")
        self._set_disconnected()
        self._schedule_retry()

    async def _async_check_too_old(self) -> bool:
        """Raise addon_too_old, and return True, when health answers but /today doesn't exist."""
        try:
            await async_health(self.http_session, self.url)
            too_old = await async_today_missing(self.http_session, self.url)
        except AddonConnectionError:
            return False
        if too_old:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                ISSUE_ADDON_TOO_OLD,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key=ISSUE_ADDON_TOO_OLD,
            )
        return too_old

    async def _async_probe_routes(self) -> None:
        """Raise addon_too_old when `/session` or `/stats` gives 404 while health answers.

        An add-on from before sessions (the workout spec §4) or before stats (the stats spec §5.1)
        connects, but lacks the route.
        """
        try:
            if not (
                await async_session_missing(self.http_session, self.url)
                or await async_stats_missing(self.http_session, self.url)
            ):
                return
            await async_health(self.http_session, self.url)
        except AddonConnectionError:
            # The connection's own handling notices an outage; the next hello probes again.
            _LOGGER.debug("The route probe could not reach the add-on")
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            ISSUE_ADDON_TOO_OLD,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=ISSUE_ADDON_TOO_OLD,
        )

    @callback
    def _handle_connect(self) -> None:
        """The ws handshake succeeded: the add-on is reachable, so the outage is over."""
        self._outage_logged = False

    @callback
    def _handle_message(self, message: Message) -> None:
        if isinstance(message, Hello):
            self._handle_hello(message)
        elif not self.connected:
            return
        elif isinstance(message, Today):
            self.today = message.data
            self._notify()
        elif isinstance(message, Session):
            self.session = message.data
            self.session_seen = True
            self._notify()
        elif isinstance(message, StatsMessage):
            self.stats = message.data
            self.stats_seen = True
            self._notify()
        elif isinstance(message, SessionEvent):
            if message.event in SESSION_EVENTS:
                self.hass.bus.async_fire(f"{DOMAIN}_{message.event}", message.session)
        elif message.event in TRAINING_DAY_EVENTS:
            self.hass.bus.async_fire(EVENT_PREFIX + message.event, message.training_day)

    @callback
    def _handle_hello(self, hello: Hello) -> None:
        if hello.api_version not in SUPPORTED_API_VERSIONS:
            _LOGGER.warning(
                "The HA Fitness add-on speaks API version %s; this integration supports %s",
                hello.api_version,
                SUPPORTED_API_VERSIONS,
            )
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                ISSUE_UNSUPPORTED_API_VERSION,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key=ISSUE_UNSUPPORTED_API_VERSION,
                translation_placeholders={
                    "api_version": str(hello.api_version),
                    "supported": ", ".join(map(str, SUPPORTED_API_VERSIONS)),
                },
            )
            self._set_disconnected()
            return
        ir.async_delete_issue(self.hass, DOMAIN, ISSUE_UNSUPPORTED_API_VERSION)
        ir.async_delete_issue(self.hass, DOMAIN, ISSUE_ADDON_TOO_OLD)
        _LOGGER.info("Connected to the HA Fitness add-on %s", hello.version)
        self._attempt = 0
        self.addon_version = hello.version
        self._update_sw_version(hello.version)
        self.connected = True
        self.session_seen = False
        self.stats_seen = False
        # Every hello deletes addon_too_old above; the probe raises it again on an older add-on.
        self.entry.async_create_background_task(
            self.hass, self._async_probe_routes(), f"{DOMAIN} route probe"
        )
        self._notify()

    @callback
    def _update_sw_version(self, version: str) -> None:
        """Set the device's software version to the add-on's (the device is made at setup)."""
        device_registry = dr.async_get(self.hass)
        device = device_registry.async_get_device_by_identifier(
            (DOMAIN, self.entry.entry_id), self.entry.entry_id
        )
        if device is not None:
            device_registry.async_update_device(device.id, sw_version=version)

    @callback
    def _log_outage(self, message: str) -> None:
        """Log a failed connect once per outage, at WARNING: never ERROR (scripts/smoke)."""
        if not self._outage_logged:
            self._outage_logged = True
            _LOGGER.warning(message, self.url)

    @callback
    def _set_disconnected(self) -> None:
        if (
            self.connected
            or self.today is not None
            or self.session_seen
            or self.stats_seen
        ):
            self.connected = False
            self.today = None
            self.session_seen = False
            self.stats_seen = False
            self._notify()

    @callback
    def _schedule_retry(self) -> None:
        if self._stopped:
            return
        delay = RECONNECT_DELAYS[min(self._attempt, len(RECONNECT_DELAYS) - 1)]
        self._attempt += 1
        self._cancel_retry = async_call_later(
            self.hass,
            delay,
            HassJob(self._retry, f"{DOMAIN} reconnect", cancel_on_shutdown=True),
        )

    @callback
    def _retry(self, _now: datetime) -> None:
        self._cancel_retry = None
        if not self._stopped:
            self.async_start()

    @callback
    def _notify(self) -> None:
        """Tell each listener, and the dispatcher; one failing listener doesn't stop the rest."""
        for update_callback in list(self._listeners):
            try:
                update_callback()
            except Exception:
                # One failing listener doesn't keep the change from the others.
                _LOGGER.warning("Error in an HA Fitness listener", exc_info=True)
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)


def usable_coordinator(hass: HomeAssistant) -> FitnessCoordinator | None:
    """Return the loaded entry's coordinator while its add-on is usable, else None.

    Usable means connected, speaking a supported API version, and with today received.
    """
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        coordinator: FitnessCoordinator = entry.runtime_data
        if coordinator.available:
            return coordinator
    return None
