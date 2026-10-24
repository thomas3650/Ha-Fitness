"""Tests for the phases of a plan and the tick (spec §3.1, §3.2), walked through REST and ws on a frozen clock."""

from datetime import datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
import httpx
import pytest

from tests.conftest import FrozenClock, MakeApp
from tests.session_helpers import (
    AGENT,
    SESSION,
    SMALL,
    create_small,
    current,
    make_session_app,
    numbers,
    ok,
    phase_of,
    set_people,
    start,
    started,
)
from tests.test_people import ELIN, THOMAS
from tests.test_scheduler import FIVE, local

WEDNESDAY_9 = local(2026, 10, 28, 9)


def _ends(view: dict[str, Any]) -> datetime:
    """Return a running view's `phase.ends_at` as an aware time."""
    return datetime.fromisoformat(view["phase"]["ends_at"])


async def _walk_by_ticks(
    client: httpx.AsyncClient, clock: FrozenClock
) -> list[dict[str, Any]]:
    """Read every phase of the running session by moving the clock to each deadline; return the views, the last finished."""
    views = [await current(client)]
    while views[-1]["status"] == "running":
        assert len(views) < 50, "the session never finishes"
        clock.set(_ends(views[-1]))
        views.append(await current(client))
    return views


@pytest.mark.parametrize(
    ("stations", "fields", "expected"),
    [
        # Countdown, switches, rests: no switch after the last interval of the last round.
        (
            2,
            {},
            [
                ("countdown", 1, 1, 5),
                ("work", 1, 1, 10),
                ("switch", 1, 1, 5),
                ("work", 1, 2, 10),
                ("switch", 1, 2, 5),
                ("rest", 1, 2, 20),
                ("work", 2, 1, 10),
                ("switch", 2, 1, 5),
                ("work", 2, 2, 10),
            ],
        ),
        # Countdown 0 and rest 0.
        (
            2,
            {"countdown_seconds": 0, "round_rest_seconds": 0},
            [
                ("work", 1, 1, 10),
                ("switch", 1, 1, 5),
                ("work", 1, 2, 10),
                ("switch", 1, 2, 5),
                ("work", 2, 1, 10),
                ("switch", 2, 1, 5),
                ("work", 2, 2, 10),
            ],
        ),
        # Switch 0.
        (
            2,
            {"switch_seconds": 0, "countdown_seconds": 10},
            [
                ("countdown", 1, 1, 10),
                ("work", 1, 1, 10),
                ("work", 1, 2, 10),
                ("rest", 1, 2, 20),
                ("work", 2, 1, 10),
                ("work", 2, 2, 10),
            ],
        ),
        # One round of one station: the work phase alone.
        (1, {"rounds": 1, "countdown_seconds": 0}, [("work", 1, 1, 10)]),
        # One station, two rounds: its switch and the rest after round 1.
        (
            1,
            {},
            [
                ("countdown", 1, 1, 5),
                ("work", 1, 1, 10),
                ("switch", 1, 1, 5),
                ("rest", 1, 1, 20),
                ("work", 2, 1, 10),
            ],
        ),
    ],
)
async def test_phase_sequence_edge_values(
    make_app: MakeApp,
    stations: int,
    fields: dict[str, Any],
    expected: list[tuple[str, int, int, int]],
) -> None:
    """Ticks walk every phase in order and complete the session; `next` walks the work phases only."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Plan", stations=FIVE[:stations], **fields)
        await start(client, program["id"], [thomas])
        views = await _walk_by_ticks(client, clock)
        await start(client, program["id"], [thomas])
        jumped = [await current(client)]
        while jumped[-1]["status"] == "running":
            jumped.append(await ok(client, "next"))
    *walked, done = views
    assert [phase_of(view) for view in walked] == expected
    assert [view["phase"]["index"] for view in walked] == list(range(len(expected)))
    assert done["status"] == "completed"
    assert done["phase"] is None
    *nexted, finished = jumped
    work = [phase for phase in expected if phase[0] == "work"]
    first = [] if expected[0][0] == "work" else [expected[0]]
    assert [phase_of(view) for view in nexted] == first + work
    assert finished["status"] == "completed"


# The phases of `SMALL` with 3 stations, as (kind, the work offset of `current`, of `next` or None).
_THREE_STATIONS = [
    ("countdown", 0, 1),
    ("work", 0, 1),
    ("switch", 1, 2),
    ("work", 1, 2),
    ("switch", 2, 0),
    ("work", 2, 0),
    # The switch after the last interval of round 1 moves on past S: to station 1 again.
    ("switch", 0, 1),
    ("rest", 0, 1),
    ("work", 0, 1),
    ("switch", 1, 2),
    ("work", 1, 2),
    # The last switch and the last work phase lead only to the last work phase: no next.
    ("switch", 2, None),
    ("work", 2, None),
]
# One station, two rounds: every phase is at station 1; after the first work phase only the last one is left.
_ONE_STATION = [
    ("countdown", 0, 0),
    ("work", 0, 0),
    ("switch", 0, None),
    ("rest", 0, None),
    ("work", 0, None),
]


@pytest.mark.parametrize(
    ("people", "stations", "table"),
    [(1, 3, _THREE_STATIONS), (2, 3, _THREE_STATIONS), (1, 1, _ONE_STATION)],
)
async def test_stations_current_and_next_per_phase_kind(
    make_app: MakeApp, people: int, stations: int, table: list[tuple[str, int, Any]]
) -> None:
    """Each phase shows §3.1's `current` and `next` per participant: participant p works at (p + i) mod S.

    Two people need two stations, so one station runs with one person.
    """
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        ids = await set_people(client, THOMAS, ELIN)
        program = await create_small(client, "Tre", stations=FIVE[:stations])
        await start(client, program["id"], ids[:people])
        *views, _done = await _walk_by_ticks(client, clock)
    assert [view["phase"]["kind"] for view in views] == [kind for kind, *_ in table]
    for view, (kind, now, then) in zip(views, table, strict=True):
        expected = [
            (
                (p + now) % stations + 1,
                None if then is None else (p + then) % stations + 1,
            )
            for p in range(people)
        ]
        assert numbers(view) == expected, (view["phase"], kind)
        for station in view["stations"]:
            number = station["current"]["number"]
            assert station["current"]["exercise_id"] == FIVE[number - 1]
            assert station["current"]["name"] == program["station_names"][number - 1]


def test_tick_moves_several_phases_without_drift_one_event_per_tick(
    make_app: MakeApp,
) -> None:
    """A read after three deadlines moves on three phases, chained from the start, with one `session` and one event.

    A read that moves nothing publishes nothing: the next message after it is the pause's `session`.
    """
    clock = FrozenClock(WEDNESDAY_9)
    app = make_session_app(clock, make_app)
    with TestClient(app) as tc:
        response = tc.put("/api/v1/people", json={"people": [THOMAS]}, headers=AGENT)
        assert response.status_code == 200, response.text
        [thomas] = [person["id"] for person in response.json()]
        document = {
            "name": "Lille",
            "weekdays": ["wed"],
            "stations": [{"exercise": exercise} for exercise in SMALL["stations"]],
            **{key: value for key, value in SMALL.items() if key != "stations"},
        }
        program = tc.post("/api/v1/programs", json=document)
        assert program.status_code == 201, program.text
        first = tc.post(
            SESSION,
            json={"program_id": program.json()["id"], "participants": [thomas]},
            headers=AGENT,
        )
        assert first.status_code == 201, first.text
        with tc.websocket_connect("/api/v1/ws") as ws:
            assert ws.receive_json()["type"] == "hello"
            assert ws.receive_json()["type"] == "today"
            # 5 + 10 + 5 s puts it at the start of phase 3; 3 s more is inside it.
            clock.set(WEDNESDAY_9 + timedelta(seconds=23))
            view = tc.get(SESSION).json()
            session_message = ws.receive_json()
            event = ws.receive_json()
            clock.advance(timedelta(seconds=1))
            assert tc.get(SESSION).status_code == 200
            paused = tc.post(f"{SESSION}/pause", headers=AGENT)
            assert paused.status_code == 200, paused.text
            after = ws.receive_json()
    assert view["phase"]["index"] == 3
    assert view["phase"]["ends_at"] == "2026-10-28T08:00:30.000Z"
    assert view["revision"] == first.json()["revision"] + 1
    assert session_message == {"type": "session", "data": view}
    assert event["type"] == "event"
    assert event["event"] == "phase_changed"
    assert event["session"]["id"] == view["id"]
    assert event["session"]["phase"] == view["phase"]
    assert after["type"] == "session"
    assert after["data"]["status"] == "paused"
