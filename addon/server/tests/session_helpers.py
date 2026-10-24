"""Shared helpers for the session tests: an app in Copenhagen time on a frozen clock, people, programs and commands.

`SMALL` is a short program of 2 stations and 2 rounds. Its phases, by index, with their start in seconds after the
start of the session:

| index | phase | start | duration |
| --- | --- | --- | --- |
| 0 | countdown | 0 | 5 |
| 1 | work, round 1, interval 1 | 5 | 10 |
| 2 | switch | 15 | 5 |
| 3 | work, round 1, interval 2 | 20 | 10 |
| 4 | switch | 30 | 5 |
| 5 | rest | 35 | 20 |
| 6 | work, round 2, interval 1 | 55 | 10 |
| 7 | switch | 65 | 5 |
| 8 | work, round 2, interval 2 | 70 | 10 |

It ends at 80 s; `totals.planned` is 75.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any

from fastapi import FastAPI
import fastmcp
from fastmcp.client.transports import FastMCPTransport
import httpx
from mcp.types import Implementation

from tests.conftest import FrozenClock, MakeApp, running
from tests.test_people import HA_URL, TOKEN, FakeHa
from tests.test_scheduler import FIVE, ZONE

SESSION = "/api/v1/session"
SESSIONS = "/api/v1/sessions"
PROGRAMS = "/api/v1/programs"
PEOPLE = "/api/v1/people"
TODAY = "/api/v1/today"
DAYS = "/api/v1/training-days"
CHANGES = "/api/v1/changes"
AGENT = {"User-Agent": "test-agent"}

SMALL: dict[str, Any] = {
    "stations": FIVE[:2],
    "rounds": 2,
    "work_seconds": 10,
    "switch_seconds": 5,
    "round_rest_seconds": 20,
    "countdown_seconds": 5,
}
# The start of each phase of `SMALL`, in seconds after the session's start, and its end.
SMALL_STARTS = [0, 5, 15, 20, 30, 35, 55, 65, 70]
SMALL_END = 80


def make_session_app(clock: FrozenClock, make_app: MakeApp) -> FastAPI:
    """Build an app in Copenhagen time on the frozen clock, reaching a fake HA so people can be set."""
    return make_app(
        settings_overrides={"timezone": ZONE, "ha_url": HA_URL, "ha_token": TOKEN},
        ha_transport=FakeHa().transport(),
        clock=clock,
    )


@asynccontextmanager
async def started(
    clock: FrozenClock, make_app: MakeApp
) -> AsyncIterator[httpx.AsyncClient]:
    """Run a session app and yield an HTTP client talking to it."""
    async with running(make_session_app(clock, make_app)) as client:
        yield client


@asynccontextmanager
async def started_with_mcp(
    clock: FrozenClock, make_app: MakeApp
) -> AsyncIterator[tuple[httpx.AsyncClient, fastmcp.Client[FastMCPTransport]]]:
    """Run a session app and yield an HTTP client and an MCP client named `claude-code`."""
    app = make_session_app(clock, make_app)
    async with (
        running(app) as client,
        fastmcp.Client(
            app.state.mcp, client_info=Implementation(name="claude-code", version="1")
        ) as mcp_client,
    ):
        yield client, mcp_client


async def set_people(client: httpx.AsyncClient, *people: dict[str, str]) -> list[int]:
    """Set the people; it must succeed. Return their ids in order."""
    response = await client.put(PEOPLE, json={"people": list(people)})
    assert response.status_code == 200, response.text
    return [person["id"] for person in response.json()]


async def create(
    client: httpx.AsyncClient,
    name: str,
    *,
    stations: list[str] = FIVE,
    weekdays: list[str] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Create a program training on Wednesdays (or `weekdays`); it must succeed. Return the stored program."""
    document = {
        "name": name,
        "weekdays": ["wed"] if weekdays is None else weekdays,
        "stations": [{"exercise": exercise} for exercise in stations],
        **fields,
    }
    response = await client.post(PROGRAMS, json=document)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def create_small(
    client: httpx.AsyncClient, name: str, **fields: Any
) -> dict[str, Any]:
    """Create the program `SMALL`, with `fields` replacing its values."""
    values = {**SMALL, **fields}
    stations = values.pop("stations")
    return await create(client, name, stations=stations, **values)


async def open_day(client: httpx.AsyncClient, program_id: int) -> int:
    """Return the id of the program's open day in `GET /today`."""
    response = await client.get(TODAY)
    assert response.status_code == 200, response.text
    [day_id] = [
        day["id"] for day in response.json()["open"] if day["program_id"] == program_id
    ]
    return int(day_id)


async def start(
    client: httpx.AsyncClient,
    program_id: int,
    participants: list[int],
    training_day_id: int | None = None,
) -> dict[str, Any]:
    """Start a session as `test-agent`; it must succeed. Return the view."""
    body: dict[str, Any] = {"program_id": program_id, "participants": participants}
    if training_day_id is not None:
        body["training_day_id"] = training_day_id
    response = await client.post(SESSION, json=body, headers=AGENT)
    assert response.status_code == 201, response.text
    view: dict[str, Any] = response.json()
    return view


async def command(client: httpx.AsyncClient, name: str) -> httpx.Response:
    """Send a session command as `test-agent`."""
    return await client.post(f"{SESSION}/{name}", headers=AGENT)


async def ok(client: httpx.AsyncClient, name: str) -> dict[str, Any]:
    """Send a session command; it must succeed. Return the view."""
    response = await command(client, name)
    assert response.status_code == 200, response.text
    view: dict[str, Any] = response.json()
    return view


async def current(client: httpx.AsyncClient) -> Any:
    """Return `GET /session` (a view or None), read as `test-agent`."""
    response = await client.get(SESSION, headers=AGENT)
    assert response.status_code == 200, response.text
    return response.json()


async def days(client: httpx.AsyncClient, start_date: str, end_date: str) -> Any:
    """Return the training days from `start_date` to `end_date`."""
    response = await client.get(DAYS, params={"from": start_date, "to": end_date})
    assert response.status_code == 200, response.text
    return response.json()


def iso(moment: datetime) -> str:
    """Write an aware UTC time the way the session view does: ISO with milliseconds and `Z`."""
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def at(begin: datetime, seconds: float) -> datetime:
    """Return `seconds` after `begin`."""
    return begin + timedelta(seconds=seconds)


def phase_of(view: dict[str, Any]) -> tuple[str, int, int, int]:
    """Return a view's phase as (kind, round, interval, duration)."""
    phase = view["phase"]
    return phase["kind"], phase["round"], phase["interval"], phase["duration"]


def numbers(view: dict[str, Any]) -> list[tuple[int, int | None]]:
    """Return each participant's (current, next) station number; next is None when null."""
    return [
        (
            station["current"]["number"],
            None if station["next"] is None else station["next"]["number"],
        )
        for station in view["stations"]
    ]
