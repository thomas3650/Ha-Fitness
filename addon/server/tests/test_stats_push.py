"""Tests for the `stats` push message (stats spec §4), through the websocket on a frozen clock in Copenhagen time.

The scheduler keeps its default 60 s interval, so only the change under test can push `stats`; the new-month test is
the one that needs the minute loop, and it runs every 0.05 s there. The session loop wakes every 0.05 s, so moving the
clock finishes a session. `receive_json()` has no timeout, so every test asserts on the exact next message, and ends
on a known message (a session start) to show that nothing more came before it. October 2026: Wed 28, Thu 29, Fri 30,
Sat 31; Sun 1 and Mon 2 November.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import FrozenClock, MakeApp
from tests.session_helpers import (
    AGENT,
    DAYS,
    PEOPLE,
    PROGRAMS,
    SESSION,
    SMALL,
    SMALL_END,
    SMALL_STARTS,
    TODAY,
    at,
    make_session_app,
)
from tests.test_people import THOMAS
from tests.test_scheduler import ZONE, local

WS = "/api/v1/ws"
STATS = "/api/v1/stats"
FAST = 0.05
WEDNESDAY_9 = local(2026, 10, 28, 9)
SMALL_TIME = SMALL_END - SMALL["countdown_seconds"]
KEPT = timedelta(minutes=5)


@contextmanager
def _client(make_app: MakeApp, clock: FrozenClock) -> Iterator[TestClient]:
    """Run a session app with the session loop every 0.05 s and the scheduler at its default 60 s."""
    app = make_session_app(clock, make_app, {"session_tick_max": FAST})
    with TestClient(app) as tc:
        yield tc


def _thomas(tc: TestClient, name: str = "Thomas") -> int:
    """Set Thomas as the one person, named `name`; return his id."""
    response = tc.put(PEOPLE, json={"people": [{**THOMAS, "name": name}]})
    assert response.status_code == 200, response.text
    [thomas] = [person["id"] for person in response.json()]
    return int(thomas)


def _program(tc: TestClient, name: str, weekdays: list[str]) -> int:
    """Create `SMALL` as `name` on `weekdays`; return its id."""
    document = {
        "name": name,
        "weekdays": weekdays,
        "stations": [{"exercise": exercise} for exercise in SMALL["stations"]],
        **{key: value for key, value in SMALL.items() if key != "stations"},
    }
    response = tc.post(PROGRAMS, json=document)
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def _open_day(tc: TestClient, program_id: int) -> int:
    """Return the id of the program's open day; reading `/today` reconciles, so call it before the change under test."""
    [day_id] = [
        day["id"]
        for day in tc.get(TODAY).json()["open"]
        if day["program_id"] == program_id
    ]
    return int(day_id)


def _start(
    tc: TestClient, program_id: int, person: int, day_id: int | None = None
) -> None:
    """Start a session; it must succeed."""
    body: dict[str, Any] = {"program_id": program_id, "participants": [person]}
    if day_id is not None:
        body["training_day_id"] = day_id
    response = tc.post(SESSION, json=body, headers=AGENT)
    assert response.status_code == 201, response.text


def _train_before(
    tc: TestClient,
    clock: FrozenClock,
    program_id: int,
    person: int,
    begin: datetime,
    *,
    keep_view: bool = False,
) -> None:
    """Before the test's connection: train the program's open day at `begin`, so `counting_from` is set.

    Only the session loop's tick pushes `session: null` when the finished view goes, at a time of its own. So unless
    `keep_view`, a connection of its own waits for that null after the 5 minutes, and it can't reach the test's
    connection later.
    """
    clock.set(begin)
    day_id = _open_day(tc, program_id)
    _start(tc, program_id, person, day_id)
    _finish(tc, clock, at(begin, SMALL_END))
    assert tc.get(SESSION).json()["status"] == "completed"
    if keep_view:
        return
    with tc.websocket_connect(WS) as ws:
        _hello(ws)
        _window_passes(clock, at(begin, SMALL_END))
        [_, null] = _next(ws, "stats", "session")
    assert null["data"] is None


def _hello(ws: Any) -> None:
    """Read `hello`, `today` and `session` of a new connection; the snapshot's `stats` comes next.

    A test reads that `stats` only after its change and its known next message, so a missing message shows up as a
    wrong one rather than a wait with no end.
    """
    assert ws.receive_json()["type"] == "hello"
    assert ws.receive_json()["type"] == "today"
    assert ws.receive_json()["type"] == "session"


def _type(message: dict[str, Any]) -> str:
    """Return a message's type, with the event's name for an event."""
    kind: str = message["type"]
    return f"event:{message['event']}" if kind == "event" else kind


def _next(ws: Any, *kinds: str) -> list[dict[str, Any]]:
    """Read one message per kind; each must be of that kind (`session`, `today`, `stats` or `event:<name>`)."""
    messages: list[dict[str, Any]] = []
    for kind in kinds:
        # Checked one by one: a missing message shows up as the next one, not as a wait with no end.
        messages.append(ws.receive_json())
        assert _type(messages[-1]) == kind, messages
    return messages


# The known next message: an extra session started by `_known`.
KNOWN = ("session", "event:session_started")


def _known(tc: TestClient, program_id: int, person: int) -> None:
    """Start an extra session, so `KNOWN` is the next to come after what the test expects."""
    _start(tc, program_id, person)


def _finish(tc: TestClient, clock: FrozenClock, moment: datetime) -> None:
    """Set the clock and read `/session`, which ticks (it doesn't reconcile), so a passed end finishes now."""
    clock.set(moment)
    assert tc.get(SESSION).status_code == 200


def _window_passes(clock: FrozenClock, ended: datetime) -> None:
    """Move past the finished view's 5 minutes after `ended`; the session loop's tick pushes `session: null`.

    The known next message after a finish: the tick doesn't reconcile, while a session start would, which checks the
    stats anyway.
    """
    clock.set(ended + KEPT + timedelta(seconds=1))


def _thomas_stats(message: dict[str, Any]) -> dict[str, Any]:
    """Return the one person's stats of a `stats` message."""
    [person] = message["data"]["people"]
    stats: dict[str, Any] = person
    return stats


def _skip(tc: TestClient, day_id: int) -> None:
    """Skip an open day; it must succeed."""
    response = tc.post(f"{DAYS}/{day_id}/skip", headers=AGENT)
    assert response.status_code == 200, response.text


def test_stats_follows_session_on_connect(make_app: MakeApp) -> None:
    """On connect `stats` follows `session`, and it is what `GET /stats` returns."""
    clock = FrozenClock(WEDNESDAY_9)
    with _client(make_app, clock) as tc:
        thomas = _thomas(tc)
        program_id = _program(tc, "Lille", ["wed"])
        with tc.websocket_connect(WS) as ws:
            hello, today, session = (ws.receive_json() for _ in range(3))
            _known(tc, program_id, thomas)
            [stats, *_] = _next(ws, "stats", *KNOWN)
        body = tc.get(STATS).json()
    assert [hello["type"], today["type"], session] == [
        "hello",
        "today",
        {"type": "session", "data": None},
    ]
    assert stats == {"type": "stats", "data": body}
    assert body["people"][0]["name"] == "Thomas"


def test_newer_queued_stats_replaces_the_snapshot(make_app: MakeApp) -> None:
    """A connect whose reconcile misses a day sends one `stats`, the newest, then that reconcile's events."""
    clock = FrozenClock(WEDNESDAY_9)
    with _client(make_app, clock) as tc:
        thomas = _thomas(tc)
        program_id = _program(tc, "Lille", ["wed", "thu", "fri"])
        _train_before(tc, clock, program_id, thomas, WEDNESDAY_9)
        clock.set(local(2026, 10, 29, 9))
        _open_day(tc, program_id)
        clock.set(local(2026, 10, 30, 9))
        with tc.websocket_connect(WS) as ws:
            _hello(ws)
            _known(tc, program_id, thomas)
            [stats, *_] = _next(ws, "stats", "event:due", "event:missed", *KNOWN)
    assert _thomas_stats(stats)["all_time"]["missed"] == 1
    assert _thomas_stats(stats)["all_time"]["done"] == 1


def test_skip_publishes_stats(make_app: MakeApp) -> None:
    """A skip after `counting_from` publishes one `stats`, after `skipped` and `today`."""
    clock = FrozenClock(WEDNESDAY_9)
    with _client(make_app, clock) as tc:
        thomas = _thomas(tc)
        program_id = _program(tc, "Lille", ["wed", "thu"])
        _train_before(tc, clock, program_id, thomas, WEDNESDAY_9)
        clock.set(local(2026, 10, 29, 9))
        day_id = _open_day(tc, program_id)
        with tc.websocket_connect(WS) as ws:
            _hello(ws)
            _skip(tc, day_id)
            _known(tc, program_id, thomas)
            [before, _, _, stats, *_] = _next(
                ws, "stats", "event:skipped", "today", "stats", *KNOWN
            )
        body = tc.get(STATS).json()
    assert _thomas_stats(before)["all_time"]["skipped"] == 0
    assert _thomas_stats(stats)["all_time"]["skipped"] == 1
    assert stats["data"]["people"] == body["people"]


def test_reconcile_that_misses_a_day_publishes_stats(make_app: MakeApp) -> None:
    """A reconcile that closes a day as missed publishes one `stats`, after the events and `today`."""
    clock = FrozenClock(WEDNESDAY_9)
    with _client(make_app, clock) as tc:
        thomas = _thomas(tc)
        program_id = _program(tc, "Lille", ["wed", "thu", "fri"])
        _train_before(tc, clock, program_id, thomas, WEDNESDAY_9)
        clock.set(local(2026, 10, 29, 9))
        _open_day(tc, program_id)
        with tc.websocket_connect(WS) as ws:
            _hello(ws)
            clock.set(local(2026, 10, 30, 9))
            assert tc.get(TODAY).status_code == 200
            _known(tc, program_id, thomas)
            [before, *_, stats, _, _] = _next(
                ws, "stats", "event:due", "event:missed", "today", "stats", *KNOWN
            )
        body = tc.get(STATS).json()
    assert _thomas_stats(before)["all_time"]["missed"] == 0
    assert _thomas_stats(stats)["all_time"]["missed"] == 1
    assert stats["data"]["people"] == body["people"]


def test_completed_day_session_publishes_stats(make_app: MakeApp) -> None:
    """A day's session completed publishes one `stats`, after `done` and `today`."""
    clock = FrozenClock(WEDNESDAY_9)
    with _client(make_app, clock) as tc:
        thomas = _thomas(tc)
        program_id = _program(tc, "Lille", ["wed"])
        day_id = _open_day(tc, program_id)
        with tc.websocket_connect(WS) as ws:
            _hello(ws)
            _start(tc, program_id, thomas, day_id)
            _finish(tc, clock, at(WEDNESDAY_9, SMALL_END))
            _window_passes(clock, at(WEDNESDAY_9, SMALL_END))
            [before, *_, stats, _] = _next(
                ws,
                "stats",
                *KNOWN,
                "session",
                "event:session_completed",
                "event:done",
                "today",
                "stats",
                "session",
            )
        body = tc.get(STATS).json()
    assert before["data"]["counting_from"] is None
    assert stats["data"]["people"] == body["people"]
    assert stats["data"]["counting_from"] == "2026-10-28"
    assert _thomas_stats(stats)["all_time"]["done"] == 1
    assert _thomas_stats(stats)["streak"] == 1


def test_counted_extra_sessions_publish_stats(make_app: MakeApp) -> None:
    """An extra session completed publishes one `stats`; so does another ended after a round."""
    clock = FrozenClock(WEDNESDAY_9)
    with _client(make_app, clock) as tc:
        thomas = _thomas(tc)
        program_id = _program(tc, "Lille", ["wed"])
        _train_before(tc, clock, program_id, thomas, WEDNESDAY_9)
        ten = local(2026, 10, 28, 10)
        clock.set(ten)
        with tc.websocket_connect(WS) as ws:
            _hello(ws)
            _start(tc, program_id, thomas)
            _finish(tc, clock, at(ten, SMALL_END))
            _window_passes(clock, at(ten, SMALL_END))
            [*_, completed, _] = _next(
                ws,
                "stats",
                *KNOWN,
                "session",
                "event:session_completed",
                "stats",
                "session",
            )
            later = clock.now()
            _start(tc, program_id, thomas)
            # Just past the end of round 1: the rest has begun.
            _finish(tc, clock, at(later, SMALL_STARTS[5] + 1))
            response = tc.post(f"{SESSION}/end", headers=AGENT)
            assert response.status_code == 200, response.text
            _window_passes(clock, clock.now())
            [*_, ended, _] = _next(
                ws,
                *KNOWN,
                "session",
                "event:phase_changed",
                "session",
                "event:session_ended",
                "stats",
                "session",
            )
        body = tc.get(STATS).json()
    assert _thomas_stats(completed)["all_time"]["done"] == 2
    assert _thomas_stats(completed)["all_time"]["extra"] == 1
    assert _thomas_stats(ended)["all_time"]["done"] == 3
    assert _thomas_stats(ended)["all_time"]["extra"] == 2
    assert ended["data"]["people"] == body["people"]


def test_first_counted_session_extra_publishes_stats(make_app: MakeApp) -> None:
    """The first counted session being an extra one publishes one `stats`, with `counting_from` set."""
    clock = FrozenClock(WEDNESDAY_9)
    with _client(make_app, clock) as tc:
        thomas = _thomas(tc)
        program_id = _program(tc, "Lille", ["wed"])
        with tc.websocket_connect(WS) as ws:
            _hello(ws)
            _start(tc, program_id, thomas)
            _finish(tc, clock, at(WEDNESDAY_9, SMALL_END))
            _window_passes(clock, at(WEDNESDAY_9, SMALL_END))
            [before, *_, stats, null] = _next(
                ws,
                "stats",
                *KNOWN,
                "session",
                "event:session_completed",
                "stats",
                "session",
            )
        body = tc.get(STATS).json()
    assert before["data"]["counting_from"] is None
    assert null["data"] is None
    assert stats["data"]["counting_from"] == "2026-10-28"
    assert _thomas_stats(stats)["all_time"] == {
        "done": 1,
        "extra": 1,
        "missed": 0,
        "skipped": 0,
        "time_trained": SMALL_TIME,
    }
    assert stats["data"]["people"] == body["people"]


def test_people_change_publishes_stats(make_app: MakeApp) -> None:
    """A rename publishes one `stats` with the new name, though `today` stays the same.

    It connects while a finished view still shows, so the known next message is the null push, which doesn't
    reconcile: only the rename's own reconcile can publish the `stats`.
    """
    clock = FrozenClock(WEDNESDAY_9)
    with _client(make_app, clock) as tc:
        thomas = _thomas(tc)
        program_id = _program(tc, "Lille", ["wed"])
        _train_before(tc, clock, program_id, thomas, WEDNESDAY_9, keep_view=True)
        with tc.websocket_connect(WS) as ws:
            _hello(ws)
            assert _thomas(tc, "Tom") == thomas
            _window_passes(clock, at(WEDNESDAY_9, SMALL_END))
            [before, stats, null] = _next(ws, "stats", "stats", "session")
    assert _thomas_stats(before)["name"] == "Thomas"
    assert _thomas_stats(stats)["name"] == "Tom"
    assert null["data"] is None


def test_uncounted_end_publishes_no_stats(make_app: MakeApp) -> None:
    """A session ended before one round changes no number, so no `stats` comes."""
    clock = FrozenClock(WEDNESDAY_9)
    with _client(make_app, clock) as tc:
        thomas = _thomas(tc)
        program_id = _program(tc, "Lille", ["wed"])
        _train_before(tc, clock, program_id, thomas, WEDNESDAY_9)
        clock.set(local(2026, 10, 28, 10))
        with tc.websocket_connect(WS) as ws:
            _hello(ws)
            _start(tc, program_id, thomas)
            response = tc.post(f"{SESSION}/end", headers=AGENT)
            assert response.status_code == 200, response.text
            _known(tc, program_id, thomas)
            [*_, ended, _, _] = _next(
                ws, "stats", *KNOWN, "session", "event:session_ended", *KNOWN
            )
    assert ended["session"]["counted"] is False


def test_unchanged_stats_publish_nothing(make_app: MakeApp) -> None:
    """A new open day and a skip before `counting_from` change no number, so no `stats` comes."""
    clock = FrozenClock(WEDNESDAY_9)
    with _client(make_app, clock) as tc:
        thomas = _thomas(tc)
        with tc.websocket_connect(WS) as ws:
            _hello(ws)
            program_id = _program(tc, "Lille", ["wed"])
            _skip(tc, _open_day(tc, program_id))
            _known(tc, program_id, thomas)
            _next(ws, "stats", "event:due", "today", "event:skipped", "today", *KNOWN)


def test_minute_loop_pushes_stats_on_a_new_month_only(make_app: MakeApp) -> None:
    """The minute loop pushes `stats` across midnight into November, and not across an ordinary midnight.

    The loop reads the clock for the reconcile, for `today` and for the stats one after the other, so a clock move
    during a run can send November's `stats` before November's `today`. Both orders are fine. When `today` comes
    first, the clock moves on to 2 November before the `stats` is read, so a missing `stats` shows up as that date's
    `today` and not as a wait with no end.
    """
    clock = FrozenClock(local(2026, 10, 30, 23, 59))
    app = make_app(
        settings_overrides={"timezone": ZONE, "scheduler_interval": FAST}, clock=clock
    )
    with TestClient(app) as tc, tc.websocket_connect(WS) as ws:
        _hello(ws)
        clock.set(local(2026, 10, 31, 0, 1))
        [before, october] = _next(ws, "stats", "today")
        clock.set(local(2026, 11, 1, 0, 1))
        first = ws.receive_json()
        if first["type"] == "stats":
            stats = first
            [november] = _next(ws, "today")
            clock.set(local(2026, 11, 2, 0, 1))
            [monday] = _next(ws, "today")
        else:
            assert first["type"] == "today", first
            november = first
            clock.set(local(2026, 11, 2, 0, 1))
            [stats, monday] = _next(ws, "stats", "today")
    assert before["data"]["month"] == "2026-10"
    assert october["data"]["date"] == "2026-10-31"
    assert november["data"]["date"] == "2026-11-01"
    assert stats["data"]["month"] == "2026-11"
    assert monday["data"]["date"] == "2026-11-02"
