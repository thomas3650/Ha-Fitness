"""Talk to the HA Fitness add-on: its REST API and its push channel (spec §3.5 and §3.6)."""

from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

# Health is a quick check; an add-on that takes longer counts as unreachable.
HEALTH_TIMEOUT = aiohttp.ClientTimeout(total=10)
# A skip is a small write; the same bound.
SKIP_TIMEOUT = aiohttp.ClientTimeout(total=10)
# Seconds between pings on the push channel; a pong missing for half that drops the connection,
# so a half-open connection is noticed.
WS_HEARTBEAT = 30.0


class AddonConnectionError(Exception):
    """The add-on could not be reached, or did not answer as an add-on does."""


class AddonHandshakeRejectedError(AddonConnectionError):
    """The add-on answered the push channel's handshake with an HTTP status."""


class TrainingDayNotFoundError(Exception):
    """The add-on knows no training day with this id (404)."""


class TrainingDayNotOpenError(Exception):
    """The training day is already closed (409)."""


@dataclass(frozen=True, slots=True)
class Hello:
    """The first message on the push channel: the add-on's version and API version."""

    version: str
    api_version: int


@dataclass(frozen=True, slots=True)
class Today:
    """What `GET /api/v1/today` returns, pushed on connect and on every change."""

    data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TrainingDayEvent:
    """One state change of a training day: due, skipped or missed."""

    event: str
    training_day: dict[str, Any]


type Message = Hello | Today | TrainingDayEvent


async def async_health(session: aiohttp.ClientSession, url: str) -> dict[str, Any]:
    """Return the body of `GET <url>/api/v1/health`."""
    try:
        async with session.get(
            f"{url}/api/v1/health", timeout=HEALTH_TIMEOUT, raise_for_status=True
        ) as response:
            body: dict[str, Any] = await response.json()
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise AddonConnectionError(str(err)) from err
    return body


async def async_today_missing(session: aiohttp.ClientSession, url: str) -> bool:
    """Return whether `GET <url>/api/v1/today` gives 404, as on an add-on older than 0.2.0."""
    try:
        async with session.get(
            f"{url}/api/v1/today", timeout=HEALTH_TIMEOUT
        ) as response:
            return response.status == HTTPStatus.NOT_FOUND
    except (aiohttp.ClientError, TimeoutError) as err:
        raise AddonConnectionError(str(err)) from err


async def async_skip(
    session: aiohttp.ClientSession,
    url: str,
    training_day_id: int,
    integration_version: str,
) -> dict[str, Any]:
    """Skip an open training day; return the day as the add-on stored it.

    Raises `TrainingDayNotFoundError` on a 404, `TrainingDayNotOpenError` on a 409, and
    `AddonConnectionError` when the add-on can't be reached or answers anything else.
    """
    try:
        async with session.post(
            f"{url}/api/v1/training-days/{training_day_id}/skip",
            headers={"User-Agent": f"ha_fitness/{integration_version}"},
            timeout=SKIP_TIMEOUT,
        ) as response:
            if response.status == HTTPStatus.NOT_FOUND:
                raise TrainingDayNotFoundError(training_day_id)
            if response.status == HTTPStatus.CONFLICT:
                raise TrainingDayNotOpenError(training_day_id)
            response.raise_for_status()
            body: dict[str, Any] = await response.json()
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise AddonConnectionError(str(err)) from err
    return body


def parse_message(raw: Any) -> Message | None:
    """Turn one push-channel message into a `Message`; unknown or malformed ones give None."""
    if not isinstance(raw, dict):
        return None
    match raw.get("type"):
        case "hello":
            version, api_version = raw.get("version"), raw.get("api_version")
            if isinstance(version, str) and isinstance(api_version, int):
                return Hello(version=version, api_version=api_version)
        case "today":
            if isinstance(data := raw.get("data"), dict):
                return Today(data=data)
        case "event":
            event, training_day = raw.get("event"), raw.get("training_day")
            if isinstance(event, str) and isinstance(training_day, dict):
                return TrainingDayEvent(event=event, training_day=training_day)
    return None


async def async_listen(
    session: aiohttp.ClientSession,
    url: str,
    on_connect: Callable[[], None],
    on_message: Callable[[Message], None],
) -> None:
    """Open `<url>/api/v1/ws`, call `on_connect`, and pass each known message to `on_message`.

    It returns when the add-on closes the channel. It raises `AddonHandshakeRejectedError`
    when the handshake gets an HTTP status, and `AddonConnectionError` when the add-on can't
    be reached or the channel breaks (a missing pong included).
    """
    try:
        async with session.ws_connect(
            f"{url}/api/v1/ws",
            timeout=aiohttp.ClientWSTimeout(ws_close=10),
            heartbeat=WS_HEARTBEAT,
        ) as ws:
            on_connect()
            async for msg in ws:
                if msg.type is aiohttp.WSMsgType.ERROR:
                    raise AddonConnectionError(str(msg.data))
                if msg.type is not aiohttp.WSMsgType.TEXT:
                    continue
                try:
                    raw = msg.json()
                except ValueError:
                    _LOGGER.debug("Ignoring a push message that isn't JSON")
                    continue
                if (message := parse_message(raw)) is not None:
                    on_message(message)
    except aiohttp.WSServerHandshakeError as err:
        raise AddonHandshakeRejectedError(str(err)) from err
    except (aiohttp.ClientError, TimeoutError) as err:
        raise AddonConnectionError(str(err)) from err
