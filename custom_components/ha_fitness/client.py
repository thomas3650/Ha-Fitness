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
# Session commands are small too.
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)
# The programs and people lists: a little longer, as the add-on's GET /people waits up to 10 s on HA.
LIST_TIMEOUT = aiohttp.ClientTimeout(total=15)
# A GIF can be a few megabytes.
MEDIA_TIMEOUT = aiohttp.ClientTimeout(total=30)

# The codes of a refused session route's `detail` (the workout spec §3.5).
SESSION_REFUSALS = ("not_found", "conflict", "invalid")
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


class SessionRefusedError(Exception):
    """The add-on refused a session route with a known `detail.code`."""

    def __init__(self, code: str) -> None:
        """Keep the add-on's code: not_found, conflict or invalid."""
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class Media:
    """An exercise's GIF or thumbnail, as the add-on served it."""

    body: bytes
    content_type: str


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


@dataclass(frozen=True, slots=True)
class Session:
    """The session view (the workout spec §3.5), or None when there is no session."""

    data: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class SessionEvent:
    """One event of a session: started, completed, ended or phase changed."""

    event: str
    session: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StatsMessage:
    """The add-on's stats (the stats spec §3.4), kept raw."""

    data: dict[str, Any]


type Message = Hello | Today | TrainingDayEvent | Session | SessionEvent | StatsMessage


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


async def _async_missing(session: aiohttp.ClientSession, url: str, path: str) -> bool:
    """Return whether `GET <url><path>` gives 404."""
    try:
        async with session.get(f"{url}{path}", timeout=HEALTH_TIMEOUT) as response:
            return response.status == HTTPStatus.NOT_FOUND
    except (aiohttp.ClientError, TimeoutError) as err:
        raise AddonConnectionError(str(err)) from err


async def async_today_missing(session: aiohttp.ClientSession, url: str) -> bool:
    """Return whether `GET <url>/api/v1/today` gives 404, as on an add-on older than 0.2.0."""
    return await _async_missing(session, url, "/api/v1/today")


async def async_session_missing(session: aiohttp.ClientSession, url: str) -> bool:
    """Return whether `GET <url>/api/v1/session` gives 404, as on an add-on from before sessions."""
    return await _async_missing(session, url, "/api/v1/session")


async def async_stats_missing(session: aiohttp.ClientSession, url: str) -> bool:
    """Return whether `GET <url>/api/v1/stats` gives 404, as on an add-on from before stats."""
    return await _async_missing(session, url, "/api/v1/stats")


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


def _user_agent(integration_version: str) -> dict[str, str]:
    return {"User-Agent": f"ha_fitness/{integration_version}"}


async def _async_session_post(
    session: aiohttp.ClientSession,
    url: str,
    path: str,
    integration_version: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST a session route; return the view.

    Raises `SessionRefusedError` on a 4xx whose `detail.code` is a known refusal, and
    `AddonConnectionError` on anything else that isn't a success.
    """
    try:
        async with session.post(
            f"{url}{path}",
            json=body,
            headers=_user_agent(integration_version),
            timeout=REQUEST_TIMEOUT,
        ) as response:
            if response.status >= HTTPStatus.BAD_REQUEST:
                if (code := await _refusal_code(response)) is not None:
                    raise SessionRefusedError(code)
                raise AddonConnectionError(f"{path} answered {response.status}")
            view: dict[str, Any] = await response.json()
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise AddonConnectionError(str(err)) from err
    return view


async def _refusal_code(response: aiohttp.ClientResponse) -> str | None:
    """Return the known `detail.code` of a refused session route, or None."""
    try:
        body = await response.json(content_type=None)
    except ValueError:
        return None
    detail = body.get("detail") if isinstance(body, dict) else None
    code = detail.get("code") if isinstance(detail, dict) else None
    return code if code in SESSION_REFUSALS else None


async def async_start_session(
    session: aiohttp.ClientSession,
    url: str,
    program_id: int,
    participants: list[int],
    training_day_id: int | None,
    integration_version: str,
) -> dict[str, Any]:
    """Start a session (`POST /api/v1/session`); return its view."""
    body: dict[str, Any] = {"program_id": program_id, "participants": participants}
    if training_day_id is not None:
        body["training_day_id"] = training_day_id
    return await _async_session_post(
        session, url, "/api/v1/session", integration_version, body
    )


async def async_session_command(
    session: aiohttp.ClientSession, url: str, command: str, integration_version: str
) -> dict[str, Any]:
    """Send pause, resume, next, previous or end (`POST /api/v1/session/{command}`); return the view."""
    return await _async_session_post(
        session, url, f"/api/v1/session/{command}", integration_version
    )


async def async_session_feeling(
    session: aiohttp.ClientSession, url: str, feeling: str, integration_version: str
) -> dict[str, Any]:
    """Send how the workout felt (`POST /api/v1/session/feeling`); return the view."""
    return await _async_session_post(
        session,
        url,
        "/api/v1/session/feeling",
        integration_version,
        {"feeling": feeling},
    )


async def _async_get_json(session: aiohttp.ClientSession, url: str, path: str) -> Any:
    try:
        async with session.get(
            f"{url}{path}", timeout=LIST_TIMEOUT, raise_for_status=True
        ) as response:
            return await response.json()
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise AddonConnectionError(str(err)) from err


async def async_programs(
    session: aiohttp.ClientSession, url: str
) -> list[dict[str, Any]]:
    """Return `GET /api/v1/programs`: every stored program, by name."""
    programs = await _async_get_json(session, url, "/api/v1/programs")
    if not isinstance(programs, list):
        raise AddonConnectionError("/api/v1/programs gave no list")
    return programs


async def async_people(
    session: aiohttp.ClientSession, url: str
) -> list[dict[str, Any]]:
    """Return the `people` list of `GET /api/v1/people`."""
    body = await _async_get_json(session, url, "/api/v1/people")
    people = body.get("people") if isinstance(body, dict) else None
    if not isinstance(people, list):
        raise AddonConnectionError("/api/v1/people gave no people list")
    return people


async def async_media(
    session: aiohttp.ClientSession, url: str, exercise_id: str, kind: str
) -> Media | None:
    """Return an exercise's GIF or thumbnail, or None when the add-on has none (404).

    The caller checks `exercise_id` and `kind`; they go into the path as they are.
    """
    try:
        async with session.get(
            f"{url}/api/v1/exercises/{exercise_id}/{kind}", timeout=MEDIA_TIMEOUT
        ) as response:
            if response.status == HTTPStatus.NOT_FOUND:
                return None
            response.raise_for_status()
            return Media(body=await response.read(), content_type=response.content_type)
    except (aiohttp.ClientError, TimeoutError) as err:
        raise AddonConnectionError(str(err)) from err


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
        case "session":
            # The key must be there: null means no session, a missing key is malformed.
            if "data" in raw and (raw["data"] is None or isinstance(raw["data"], dict)):
                return Session(data=raw["data"])
        case "stats":
            if isinstance(data := raw.get("data"), dict):
                return StatsMessage(data=data)
        case "event":
            event = raw.get("event")
            if not isinstance(event, str):
                return None
            if isinstance(training_day := raw.get("training_day"), dict):
                return TrainingDayEvent(event=event, training_day=training_day)
            if isinstance(session_data := raw.get("session"), dict):
                return SessionEvent(event=event, session=session_data)
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
