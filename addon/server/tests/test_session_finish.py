"""Tests for finishing a session, the training day and program under it, history and the view (spec §3.4, §3.5).

Through REST and MCP on a frozen clock in Copenhagen time, mostly on the program `SMALL` (its phases are in
`tests/session_helpers.py`).
"""

from datetime import date, datetime, timedelta
from typing import Any

from fastmcp.exceptions import ToolError
import pytest

from tests.conftest import FrozenClock, MakeApp
from tests.session_helpers import (
    CHANGES,
    PROGRAMS,
    SESSION,
    SESSIONS,
    SMALL,
    SMALL_END,
    SMALL_STARTS,
    TODAY,
    at,
    create_small,
    current,
    days,
    iso,
    ok,
    open_day,
    set_people,
    start,
    started,
    started_with_mcp,
)
from tests.test_people import ELIN, THOMAS
from tests.test_scheduler import ZONE, local

WEDNESDAY_9 = local(2026, 10, 28, 9)
PLANNED = SMALL_END - SMALL["countdown_seconds"]


def _local_date(moment: str) -> date:
    """Return the Copenhagen date of a view's UTC time."""
    return datetime.fromisoformat(moment).astimezone(ZONE).date()


def _statuses(listed: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    """Return the training days as {(program name, date): status}."""
    return {(day["program_name"], day["date"]): day["status"] for day in listed}


async def _changes(client: Any, action: str) -> list[dict[str, Any]]:
    """Return the change-log rows of one action, newest first."""
    response = await client.get(CHANGES, params={"limit": 100})
    assert response.status_code == 200, response.text
    return [row for row in response.json() if row["action"] == action]


async def test_end_with_zero_rounds_not_counted_day_open(make_app: MakeApp) -> None:
    """Ending on the last work phase of round 1 counts no round: not counted, and the day stays open."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        day_id = await open_day(client, program["id"])
        await start(client, program["id"], [thomas], day_id)
        clock.set(at(WEDNESDAY_9, SMALL_STARTS[3] + 5))
        ended = await ok(client, "end")
        today = (await client.get(TODAY)).json()
        listed = await days(client, "2026-10-28", "2026-10-28")
    assert ended["status"] == "ended"
    assert ended["rounds_completed"] == 0
    assert ended["counted"] is False
    assert [day["id"] for day in today["open"]] == [day_id]
    assert _statuses(listed) == {("Lille", "2026-10-28"): "open"}


@pytest.mark.parametrize("index", [4, 5, 6])
async def test_end_after_one_round_counted_day_done(
    make_app: MakeApp, index: int
) -> None:
    """Ending once round 1's last work phase is behind counts one round and closes the day as done."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        day_id = await open_day(client, program["id"])
        await start(client, program["id"], [thomas], day_id)
        clock.set(at(WEDNESDAY_9, SMALL_STARTS[index] + 1))
        ended = await ok(client, "end")
        today = (await client.get(TODAY)).json()
        listed = await days(client, "2026-10-28", "2026-10-28")
        [logged] = await _changes(client, "session.ended")
    assert ended["status"] == "ended"
    assert ended["rounds_completed"] == 1
    assert ended["counted"] is True
    assert ended["training_day_id"] == day_id
    assert today["open"] == []
    assert _statuses(listed) == {("Lille", "2026-10-28"): "done"}
    assert logged["client"] == "rest:test-agent"
    assert logged["target"] == f"session:{ended['id']}"


async def test_completed(make_app: MakeApp) -> None:
    """A tick long after the end completes the session at the last deadline, with no drift; the day is done."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        day_id = await open_day(client, program["id"])
        await start(client, program["id"], [thomas], day_id)
        clock.set(at(WEDNESDAY_9, SMALL_END + 30))
        done = await current(client)
        listed = await days(client, "2026-10-28", "2026-10-28")
    assert done["status"] == "completed"
    assert done["counted"] is True
    assert done["rounds_completed"] == 2
    assert done["started_at"] == iso(at(WEDNESDAY_9, 5))
    assert done["ended_at"] == iso(at(WEDNESDAY_9, SMALL_END))
    assert done["time_trained"] == PLANNED
    assert type(done["time_trained"]) is int
    assert _statuses(listed) == {("Lille", "2026-10-28"): "done"}


async def test_done_late_and_not_late_across_midnight(make_app: MakeApp) -> None:
    """Done late: a late day's session starts on a later local date. Across midnight: it starts on the day's date.

    Lateness is derived (spec §3.4): the day is `done` either way, and the session's `started_at` gives its date.
    Across midnight the new date has a training day of its own, so reconcile would close the day as missed.
    """
    # Thursday 29 October: Wednesday's day of Lille is late, as no program trains on Thursdays yet.
    clock = FrozenClock(local(2026, 10, 28, 9))
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        late_day = await open_day(client, program["id"])
        clock.set(local(2026, 10, 29, 9))
        late = await start(client, program["id"], [thomas], late_day)
        clock.set(at(local(2026, 10, 29, 9), SMALL_STARTS[5]))
        late_end = await ok(client, "end")
        await create_small(client, "Torsdag", weekdays=["thu"])
        # Wednesday 4 November, 23:59:50: the session crosses into Thursday, which has Torsdag's day.
        begin = local(2026, 11, 4, 23, 59) + timedelta(seconds=50)
        clock.set(begin)
        night_day = await open_day(client, program["id"])
        night = await start(client, program["id"], [thomas], night_day)
        clock.set(at(begin, SMALL_STARTS[5] + 1))
        today = (await client.get(TODAY)).json()
        night_end = await ok(client, "end")
        listed = await days(client, "2026-10-28", "2026-11-05")
    statuses = _statuses(listed)
    assert late_end["counted"] is True
    assert statuses[("Lille", "2026-10-28")] == "done"
    assert _local_date(late["server_time"]) == date(2026, 10, 29)
    assert _local_date(late_end["started_at"]) > date(2026, 10, 28)
    assert today["date"] == "2026-11-05"
    assert {(day["program_name"], day["state"]) for day in today["open"]} == {
        ("Lille", "late"),
        ("Torsdag", "due"),
    }
    assert night_end["counted"] is True
    assert statuses[("Lille", "2026-11-04")] == "done"
    assert _local_date(night["server_time"]) == date(2026, 11, 4)
    assert _local_date(night_end["started_at"]) == date(2026, 11, 4)
    assert _local_date(night_end["ended_at"]) == date(2026, 11, 5)


@pytest.mark.parametrize("paused", [False, True], ids=["running", "paused"])
async def test_reconcile_skips_in_session_day(make_app: MakeApp, paused: bool) -> None:
    """A day stays open past midnight while its session runs or is paused; once ended uncounted it is missed."""
    # 23:59:50 on Wednesday; 12 s later it is Thursday, with the session still in its first work phase.
    begin = local(2026, 10, 28, 23, 59) + timedelta(seconds=50)
    clock = FrozenClock(begin)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        await create_small(client, "Torsdag", weekdays=["thu"])
        day_id = await open_day(client, program["id"])
        await start(client, program["id"], [thomas], day_id)
        clock.set(at(begin, 7))
        if paused:
            await ok(client, "pause")
        clock.set(at(begin, 12))
        during = _statuses(await days(client, "2026-10-28", "2026-10-29"))
        await ok(client, "end")
        after = _statuses(await days(client, "2026-10-28", "2026-10-29"))
    assert during == {
        ("Lille", "2026-10-28"): "open",
        ("Torsdag", "2026-10-29"): "open",
    }
    assert after[("Lille", "2026-10-28")] == "missed"


@pytest.mark.parametrize("paused", [False, True], ids=["running", "paused"])
async def test_skip_in_session_day_is_409(make_app: MakeApp, paused: bool) -> None:
    """Skipping the day of a running or paused session is a 409 through REST and an error through MCP."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started_with_mcp(clock, make_app) as (client, mcp_client):
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        day_id = await open_day(client, program["id"])
        await start(client, program["id"], [thomas], day_id)
        if paused:
            await ok(client, "pause")
        response = await client.post(f"/api/v1/training-days/{day_id}/skip")
        with pytest.raises(ToolError):
            await mcp_client.call_tool("skip_training_day", {"training_day_id": day_id})
        listed = await days(client, "2026-10-28", "2026-10-28")
        await ok(client, "end")
        after = await client.post(f"/api/v1/training-days/{day_id}/skip")
    assert response.status_code == 409, response.text
    assert isinstance(response.json()["detail"], str)
    assert _statuses(listed) == {("Lille", "2026-10-28"): "open"}
    assert after.status_code == 200, after.text


@pytest.mark.parametrize("extra", [False, True], ids=["training day", "extra"])
async def test_program_off_put_active_false_or_delete_during_session_is_409(
    make_app: MakeApp, extra: bool
) -> None:
    """Switching off, a PUT with `active: false` and a delete all give 409 while the program's session is active."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        other = await create_small(client, "Anden")
        program_id = program["id"]
        day_id = None if extra else await open_day(client, program_id)
        await start(client, program_id, [thomas], day_id)
        document = program["program"]
        refused = {
            "off": await client.put(
                f"{PROGRAMS}/{program_id}/active", json={"active": False}
            ),
            "put": await client.put(
                f"{PROGRAMS}/{program_id}", json={**document, "active": False}
            ),
            "delete": await client.delete(f"{PROGRAMS}/{program_id}"),
        }
        await ok(client, "pause")
        refused["delete paused"] = await client.delete(f"{PROGRAMS}/{program_id}")
        renamed = await client.put(
            f"{PROGRAMS}/{program_id}", json={**document, "rounds": 3}
        )
        other_off = await client.put(
            f"{PROGRAMS}/{other['id']}/active", json={"active": False}
        )
        still = (await client.get(f"{PROGRAMS}/{program_id}")).json()
        await ok(client, "end")
        deleted = await client.delete(f"{PROGRAMS}/{program_id}")
    for case, response in refused.items():
        assert response.status_code == 409, (case, response.text)
        assert response.json() == {"detail": "A session for this program is running"}
    assert still["program"]["active"] is True
    assert renamed.status_code == 200, renamed.text
    assert other_off.status_code == 200, other_off.text
    assert deleted.status_code == 204, deleted.text


async def test_extra_session_closes_no_day(make_app: MakeApp) -> None:
    """A completed extra session leaves the program's due day open."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        day_id = await open_day(client, program["id"])
        await start(client, program["id"], [thomas])
        clock.set(at(WEDNESDAY_9, SMALL_END))
        done = await current(client)
        today = (await client.get(TODAY)).json()
    assert done["status"] == "completed"
    assert done["counted"] is True
    assert done["training_day_id"] is None
    assert [day["id"] for day in today["open"]] == [day_id]


async def test_one_session_at_a_time_paused(make_app: MakeApp) -> None:
    """A paused session blocks another start with 409; once it ends, a new one starts."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        thomas, elin = await set_people(client, THOMAS, ELIN)
        program = await create_small(client, "Lille")
        await start(client, program["id"], [thomas])
        await ok(client, "pause")
        refused = await client.post(
            SESSION, json={"program_id": program["id"], "participants": [elin]}
        )
        await ok(client, "end")
        again = await client.post(
            SESSION, json={"program_id": program["id"], "participants": [elin]}
        )
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "conflict"
    assert again.status_code == 201, again.text


async def test_counting_from_set_once(make_app: MakeApp) -> None:
    """`counting_from` is null until a counted session, then the local date of its end; later ones keep it."""
    begin = local(2026, 10, 28, 23, 59)
    clock = FrozenClock(begin)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        empty = (await client.get(SESSIONS)).json()
        await start(client, program["id"], [thomas])
        clock.set(at(begin, 10))
        await ok(client, "end")
        uncounted = (await client.get(SESSIONS)).json()
        # Started 23:59:20 on Wednesday, ended in round 2 at 00:00:16 on Thursday (local), 23:00:16 on Wednesday in UTC.
        clock.set(at(begin, 20))
        await start(client, program["id"], [thomas])
        clock.set(at(begin, 20 + SMALL_STARTS[6] + 1))
        await ok(client, "end")
        first = (await client.get(SESSIONS)).json()
        clock.set(local(2026, 11, 4, 9))
        await start(client, program["id"], [thomas])
        clock.set(at(local(2026, 11, 4, 9), SMALL_END))
        await current(client)
        later = (await client.get(SESSIONS)).json()
    assert empty == {"counting_from": None, "sessions": []}
    assert uncounted["counting_from"] is None
    assert len(uncounted["sessions"]) == 1
    assert first["counting_from"] == "2026-10-29"
    assert later["counting_from"] == "2026-10-29"
    assert len(later["sessions"]) == 3


async def test_participant_rows_for_finished_sessions(make_app: MakeApp) -> None:
    """Every finished session, counted or not, lists its participants by name, also after a person is removed."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        thomas, elin = await set_people(client, THOMAS, ELIN)
        program = await create_small(client, "Lille")
        first = await start(client, program["id"], [thomas, elin])
        clock.set(at(WEDNESDAY_9, 10))
        await ok(client, "end")
        clock.set(at(WEDNESDAY_9, 100))
        second = await start(client, program["id"], [elin])
        clock.set(at(WEDNESDAY_9, 100 + SMALL_END))
        await current(client)
        await set_people(client, THOMAS)
        history = (await client.get(SESSIONS)).json()
        one = (await client.get(SESSIONS, params={"limit": 1})).json()
        bad = [
            await client.get(SESSIONS, params={"limit": limit})
            for limit in (0, 101, "x")
        ]
    sessions = history["sessions"]
    assert [view["id"] for view in sessions] == [second["id"], first["id"]]
    assert [view["status"] for view in sessions] == ["completed", "ended"]
    assert [view["counted"] for view in sessions] == [True, False]
    assert sessions[0]["participants"] == [{"id": elin, "name": "Elin"}]
    assert sessions[1]["participants"] == [
        {"id": thomas, "name": "Thomas"},
        {"id": elin, "name": "Elin"},
    ]
    for view in sessions:
        assert view["phase"] is None
        assert view["next_phase"] is None
        assert view["stations"] is None
        assert type(view["time_trained"]) is int
    assert sessions[0]["time_trained"] == PLANNED
    assert sessions[1]["time_trained"] == 5
    assert [view["id"] for view in one["sessions"]] == [second["id"]]
    for response in bad:
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["code"] == "invalid"


async def test_get_session_keeps_finished_view_five_minutes(make_app: MakeApp) -> None:
    """`GET /session` gives the finished view, the same as in history, until 5 minutes after the end; then null."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        await start(client, program["id"], [thomas])
        clock.set(at(WEDNESDAY_9, 30))
        ended = await ok(client, "end")
        clock.set(at(WEDNESDAY_9, 30 + 299))
        kept = await current(client)
        [listed] = (await client.get(SESSIONS)).json()["sessions"]
        clock.set(at(WEDNESDAY_9, 30 + 300))
        gone = await current(client)
    assert kept["status"] == "ended"
    assert kept["phase"] is None
    assert kept["stations"] is None
    for view in (ended, kept, listed):
        view.pop("server_time")
    assert kept == ended
    assert listed == ended
    assert gone is None


async def test_revision_increases(make_app: MakeApp) -> None:
    """Every change raises the revision: pause, resume, next, previous, a tick that moves on, and the end."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        views = [await start(client, program["id"], [thomas])]
        clock.set(at(WEDNESDAY_9, 1))
        views += [
            await ok(client, name) for name in ("pause", "resume", "next", "previous")
        ]
        clock.set(at(WEDNESDAY_9, 1 + 10))
        views.append(await current(client))
        views.append(await ok(client, "end"))
    revisions = [view["revision"] for view in views]
    assert revisions == sorted(set(revisions))
    assert len(set(revisions)) == len(views)
    assert views[-2]["phase"]["kind"] == "switch"


async def test_change_log_completed_by_tick_client_addon(make_app: MakeApp) -> None:
    """A completion by the tick is logged by `addon`, even when a request's read ran it; `next` logs its client.

    Pause, resume, next and previous log nothing.
    """
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        ticked = await start(client, program["id"], [thomas])
        for name in ("pause", "resume", "next", "previous"):
            await ok(client, name)
        clock.set(at(WEDNESDAY_9, 10 * SMALL_END))
        await current(client)
        clock.advance(timedelta(minutes=10))
        commanded = await start(client, program["id"], [thomas])
        clock.advance(timedelta(seconds=SMALL_STARTS[8]))
        await ok(client, "next")
        completed = await _changes(client, "session.completed")
        response = await client.get(CHANGES, params={"limit": 100})
    assert [(row["client"], row["target"]) for row in completed] == [
        ("rest:test-agent", f"session:{commanded['id']}"),
        ("addon", f"session:{ticked['id']}"),
    ]
    actions = {row["action"] for row in response.json()}
    assert {action for action in actions if action.startswith("session.")} == {
        "session.started",
        "session.completed",
    }
