"""Hold the connection to the add-on and what it last pushed (spec §4.2)."""

from collections.abc import Callable
from datetime import datetime
import logging
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HassJob, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later

from .client import (
    AddonConnectionError,
    AddonHandshakeRejectedError,
    Hello,
    Message,
    Today,
    async_health,
    async_listen,
    async_today_missing,
)
from .const import DOMAIN

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
    `today` message, and None while not connected.
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
        self.session = session
        self.url = url
        self.integration_version = integration_version
        self.connected = False
        self.today: dict[str, Any] | None = None
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

    async def _async_connect(self) -> None:
        """Hold one connection until it ends, then schedule the next attempt."""
        try:
            await async_listen(self.session, self.url, self._handle_message)
        except AddonHandshakeRejectedError:
            if await self._async_check_too_old():
                self._log_outage("The HA Fitness add-on at %s is too old; retrying")
            else:
                self._log_outage(UNREACHABLE)
        except AddonConnectionError:
            self._log_outage(UNREACHABLE)
        else:
            _LOGGER.info("The HA Fitness add-on closed the connection")
        self._set_disconnected()
        self._schedule_retry()

    async def _async_check_too_old(self) -> bool:
        """Raise addon_too_old, and return True, when health answers but /today doesn't exist."""
        try:
            await async_health(self.session, self.url)
            too_old = await async_today_missing(self.session, self.url)
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

    @callback
    def _handle_message(self, message: Message) -> None:
        if isinstance(message, Hello):
            self._handle_hello(message)
        elif isinstance(message, Today) and self.connected:
            self.today = message.data
            self._notify()

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
            return
        ir.async_delete_issue(self.hass, DOMAIN, ISSUE_UNSUPPORTED_API_VERSION)
        ir.async_delete_issue(self.hass, DOMAIN, ISSUE_ADDON_TOO_OLD)
        _LOGGER.info("Connected to the HA Fitness add-on %s", hello.version)
        self._attempt = 0
        self._outage_logged = False
        self.addon_version = hello.version
        self.connected = True
        self._notify()

    @callback
    def _log_outage(self, message: str) -> None:
        """Log a failed connect once per outage, at WARNING: never ERROR (scripts/smoke)."""
        if not self._outage_logged:
            self._outage_logged = True
            _LOGGER.warning(message, self.url)

    @callback
    def _set_disconnected(self) -> None:
        if self.connected or self.today is not None:
            self.connected = False
            self.today = None
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
        for update_callback in list(self._listeners):
            update_callback()
