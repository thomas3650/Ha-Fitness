"""Tests for starting and reading a session (spec §3.1, §3.5), through REST with a frozen clock in Copenhagen time."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import httpx
import pytest

from tests.conftest import FrozenClock, MakeApp, running
from tests.test_people import ELIN, HA_URL, THOMAS, TOKEN, FakeHa
from tests.test_scheduler import FIVE, ZONE, local

SESSION = "/api/v1/session"
PROGRAMS = "/api/v1/programs"
PEOPLE = "/api/v1/people"
TODAY = "/api/v1/today"
CHANGES = "/api/v1/changes"
# Wednesday 2026-10-28, 09:00 in Copenhagen (UTC+1): 08:00 UTC.
WEDNESDAY_9 = local(2026, 10, 28, 9)


@asynccontextmanager
async def started(
    clock: FrozenClock, make_app: MakeApp
) -> AsyncIterator[httpx.AsyncClient]:
    """Run an app in Copenhagen time on the frozen clock, reaching a fake HA so people can be set."""
    app = make_app(
        settings_overrides={"timezone": ZONE, "ha_url": HA_URL, "ha_token": TOKEN},
        ha_transport=FakeHa().transport(),
        clock=clock,
    )
    async with running(app) as client:
        yield client


async def _set_people(client: httpx.AsyncClient, *people: dict[str, str]) -> list[int]:
    """Set the people; it must succeed. Return their ids in order."""
    response = await client.put(PEOPLE, json={"people": list(people)})
    assert response.status_code == 200, response.text
    return [person["id"] for person in response.json()]


async def _create(
    client: httpx.AsyncClient, name: str, *, stations: list[str] = FIVE, **fields: Any
) -> dict[str, Any]:
    """Create a program training on Wednesdays; it must succeed. Return the stored program."""
    document = {
        "name": name,
        "weekdays": ["wed"],
        "stations": [{"exercise": exercise} for exercise in stations],
        **fields,
    }
    response = await client.post(PROGRAMS, json=document)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def _open_day(client: httpx.AsyncClient, program_id: int) -> int:
    """Return the id of the program's open day in `GET /today`."""
    response = await client.get(TODAY)
    assert response.status_code == 200, response.text
    [day_id] = [
        day["id"] for day in response.json()["open"] if day["program_id"] == program_id
    ]
    return int(day_id)


async def _start(
    client: httpx.AsyncClient,
    program_id: int,
    participants: list[int],
    training_day_id: int | None = None,
) -> httpx.Response:
    """Start a session as the client `test-agent`."""
    body: dict[str, Any] = {"program_id": program_id, "participants": participants}
    if training_day_id is not None:
        body["training_day_id"] = training_day_id
    return await client.post(SESSION, json=body, headers={"User-Agent": "test-agent"})


def _station(program: dict[str, Any], index: int) -> dict[str, Any]:
    """Return a station of the view by its 0-based index in the program."""
    return {
        "number": index + 1,
        "exercise_id": program["program"]["stations"][index]["exercise"],
        "name": program["station_names"][index],
    }


async def test_get_session_is_null_without_session(make_app: MakeApp) -> None:
    """With no session ever started, `GET /session` is null."""
    async with started(FrozenClock(WEDNESDAY_9), make_app) as client:
        response = await client.get(SESSION)
    assert response.status_code == 200
    assert response.json() is None


async def test_start_returns_view_at_phase_0(make_app: MakeApp) -> None:
    """A start on a training day gives the view at the countdown, participants in people order; `GET` gives it too."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        thomas, elin = await _set_people(client, THOMAS, ELIN)
        program = await _create(client, "Onsdag")
        day_id = await _open_day(client, program["id"])
        response = await _start(client, program["id"], [elin, thomas], day_id)
        assert response.status_code == 201, response.text
        view = response.json()
        clock.advance(timedelta(seconds=2))
        again = (await client.get(SESSION)).json()
    assert isinstance(view.pop("id"), int)
    assert view == {
        "revision": 1,
        "status": "running",
        "counted": False,
        "program_name": "Onsdag",
        "training_day_id": day_id,
        "participants": [
            {"id": thomas, "name": "Thomas"},
            {"id": elin, "name": "Elin"},
        ],
        "phase": {
            "index": 0,
            "kind": "countdown",
            "round": 1,
            "interval": 1,
            "duration": 5,
            "ends_at": "2026-10-28T08:00:05.000Z",
            "remaining": None,
        },
        "next_phase": {"kind": "work", "duration": 45},
        "stations": [
            {"current": _station(program, 0), "next": _station(program, 1)},
            {"current": _station(program, 1), "next": _station(program, 2)},
        ],
        "totals": {"planned": 1725, "rounds": 5, "stations": 5},
        "started_at": None,
        "ended_at": None,
        "rounds_completed": 0,
        "time_trained": 0,
        "server_time": "2026-10-28T08:00:00.000Z",
    }
    assert again.pop("server_time") == "2026-10-28T08:00:02.000Z"
    view.pop("server_time")
    assert again == {"id": again["id"], **view}


async def test_start_without_countdown_begins_at_work(make_app: MakeApp) -> None:
    """With countdown 0 an extra session starts at the first work phase; `started_at` is now and time trained is live."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        [thomas] = await _set_people(client, THOMAS)
        program = await _create(client, "Hurtig", countdown_seconds=0)
        response = await _start(client, program["id"], [thomas])
        assert response.status_code == 201, response.text
        view = response.json()
        clock.advance(timedelta(seconds=10))
        later = (await client.get(SESSION)).json()
    assert view["training_day_id"] is None
    assert view["phase"] == {
        "index": 0,
        "kind": "work",
        "round": 1,
        "interval": 1,
        "duration": 45,
        "ends_at": "2026-10-28T08:00:45.000Z",
        "remaining": None,
    }
    assert view["next_phase"] == {"kind": "switch", "duration": 15}
    assert view["stations"] == [
        {"current": _station(program, 0), "next": _station(program, 1)}
    ]
    assert view["started_at"] == "2026-10-28T08:00:00.000Z"
    assert view["time_trained"] == 0
    assert later["time_trained"] == 10
    assert later["phase"] == view["phase"]
    assert later["server_time"] == "2026-10-28T08:00:10.000Z"


@pytest.mark.parametrize(
    ("stations", "fields", "planned"),
    [
        # 5 x 5 x (45 + 15) + 4 x 60, less the last switch: 1740 - 15.
        (FIVE, {}, 1725),
        # 3 x 2 x (30 + 10) + 1 x 20, less the last switch; the countdown of 10 is left out.
        (
            FIVE[:3],
            {
                "rounds": 2,
                "work_seconds": 30,
                "switch_seconds": 10,
                "round_rest_seconds": 20,
                "countdown_seconds": 10,
            },
            250,
        ),
        # No switches and no rests: 5 x 3 x 45.
        (FIVE, {"rounds": 3, "switch_seconds": 0, "round_rest_seconds": 0}, 675),
        # One station, one round: only the work phase.
        (
            FIVE[:1],
            {
                "rounds": 1,
                "work_seconds": 10,
                "switch_seconds": 0,
                "countdown_seconds": 0,
            },
            10,
        ),
        # One station, two rounds with a switch: work, switch, rest, work.
        (
            FIVE[:1],
            {
                "rounds": 2,
                "work_seconds": 20,
                "switch_seconds": 5,
                "round_rest_seconds": 30,
            },
            75,
        ),
    ],
)
async def test_planned_total_excludes_countdown_and_last_switch(
    make_app: MakeApp, stations: list[str], fields: dict[str, Any], planned: int
) -> None:
    """`totals.planned` sums the work, switch and rest phases, without the countdown and the switch after the last interval."""
    async with started(FrozenClock(WEDNESDAY_9), make_app) as client:
        [thomas] = await _set_people(client, THOMAS)
        program = await _create(client, "Plan", stations=stations, **fields)
        response = await _start(client, program["id"], [thomas])
    assert response.status_code == 201, response.text
    assert response.json()["totals"] == {
        "planned": planned,
        "rounds": program["program"]["rounds"],
        "stations": len(stations),
    }


async def test_start_validation_codes(make_app: MakeApp) -> None:
    """Each start rule of spec §3.5 gives its status and `detail.code`; none starts a session or logs a change."""
    async with started(FrozenClock(WEDNESDAY_9), make_app) as client:
        thomas, elin = await _set_people(client, THOMAS, ELIN)
        onsdag = (await _create(client, "Onsdag"))["id"]
        other = (await _create(client, "Anden"))["id"]
        skipped = (await _create(client, "Sprunget"))["id"]
        single = (await _create(client, "En", stations=FIVE[:1]))["id"]
        off = (await _create(client, "Slukket", active=False, weekdays=[]))["id"]
        onsdag_day = await _open_day(client, onsdag)
        other_day = await _open_day(client, other)
        skipped_day = await _open_day(client, skipped)
        skip = await client.post(f"/api/v1/training-days/{skipped_day}/skip")
        assert skip.status_code == 200, skip.text
        changes_before = (await client.get(CHANGES)).json()
        cases: list[tuple[str, int, list[int], int | None, int, str]] = [
            ("unknown program", 999, [thomas], None, 404, "not_found"),
            ("unknown person", onsdag, [thomas, 999], None, 404, "not_found"),
            ("unknown training day", onsdag, [thomas], 999, 404, "not_found"),
            ("program not active", off, [thomas], None, 409, "conflict"),
            ("training day not open", skipped, [thomas], skipped_day, 409, "conflict"),
            (
                "training day of another program",
                onsdag,
                [thomas],
                other_day,
                409,
                "conflict",
            ),
            ("no participants", onsdag, [], None, 422, "invalid"),
            ("more than two", onsdag, [thomas, elin, elin], None, 422, "invalid"),
            ("duplicates", onsdag, [thomas, thomas], None, 422, "invalid"),
            (
                "more than the station count",
                single,
                [thomas, elin],
                None,
                422,
                "invalid",
            ),
        ]
        for case, program_id, participants, day_id, status, code in cases:
            response = await _start(client, program_id, participants, day_id)
            assert response.status_code == status, (case, response.text)
            detail = response.json()["detail"]
            assert detail["code"] == code, case
            assert isinstance(detail["message"], str), case
            assert set(detail) == {"code", "message"}, case
        assert (await client.get(SESSION)).json() is None
        assert (await client.get(CHANGES)).json() == changes_before
        first = await _start(client, onsdag, [thomas], onsdag_day)
        assert first.status_code == 201, first.text
        response = await _start(client, other, [elin], other_day)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "conflict"


async def test_one_session_at_a_time_running(make_app: MakeApp) -> None:
    """While a session runs another start is a 409 `conflict`, and `GET /session` still gives the first."""
    async with started(FrozenClock(WEDNESDAY_9), make_app) as client:
        thomas, elin = await _set_people(client, THOMAS, ELIN)
        first = await _create(client, "Første")
        second = await _create(client, "Anden")
        started_view = (await _start(client, first["id"], [thomas])).json()
        response = await _start(client, second["id"], [elin])
        current = (await client.get(SESSION)).json()
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "conflict"
    assert current["id"] == started_view["id"]
    assert current["program_name"] == "Første"


async def test_participant_names_frozen_in_view(make_app: MakeApp) -> None:
    """Renaming and removing people after the start leaves the session's participants as they were."""
    async with started(FrozenClock(WEDNESDAY_9), make_app) as client:
        thomas, elin = await _set_people(client, THOMAS, ELIN)
        program = await _create(client, "Onsdag")
        assert (await _start(client, program["id"], [thomas, elin])).status_code == 201
        await _set_people(client, {**THOMAS, "name": "Tom"})
        view = (await client.get(SESSION)).json()
    assert view["participants"] == [
        {"id": thomas, "name": "Thomas"},
        {"id": elin, "name": "Elin"},
    ]


async def test_start_logs_session_started(make_app: MakeApp) -> None:
    """A start logs one `session.started` row with the client of the request."""
    async with started(FrozenClock(WEDNESDAY_9), make_app) as client:
        thomas, elin = await _set_people(client, THOMAS, ELIN)
        program = await _create(client, "Onsdag")
        view = (await _start(client, program["id"], [thomas, elin])).json()
        [newest] = (await client.get(CHANGES, params={"limit": 1})).json()
    assert {key: newest[key] for key in ("client", "action", "target", "summary")} == {
        "client": "rest:test-agent",
        "action": "session.started",
        "target": f"session:{view['id']}",
        "summary": "Started session of Onsdag for Thomas, Elin",
    }
