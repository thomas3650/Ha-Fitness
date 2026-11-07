"""Tests for `totals.marks` (timer band spec §3): where each round after the first and the cool-down start.

A mark is in seconds into `totals.planned`, the countdown left out. A round starts at its first work; the rest after
a round belongs to that round. Through REST on a frozen clock in Copenhagen time.
"""

from typing import Any

import pytest

from tests.conftest import FrozenClock, MakeApp
from tests.session_helpers import (
    SESSIONS,
    create,
    current,
    ok,
    set_people,
    start,
    started,
)
from tests.test_people import THOMAS
from tests.test_scheduler import FIVE, local

WEDNESDAY_9 = local(2026, 10, 28, 9)
COOLDOWN: dict[str, Any] = {
    "stretches": [{"exercise": "0690"}, {"exercise": "1378"}],
    "hold_seconds": 30,
    "change_seconds": 10,
}
# 3 rounds of 2 stations: a round is 40 + 10 + 40 = 90 s, then a round rest of 60 s.
WITH_REST: dict[str, Any] = {
    "rounds": 3,
    "work_seconds": 40,
    "switch_seconds": 10,
    "round_rest_seconds": 60,
    "countdown_seconds": 10,
}


@pytest.mark.parametrize(
    ("stations", "fields", "marks"),
    [
        pytest.param(
            FIVE[:3],
            {"rounds": 1, "countdown_seconds": 10},
            [],
            id="one round, no cool-down",
        ),
        pytest.param(FIVE[:2], WITH_REST, [150, 300], id="rounds with a round rest"),
        pytest.param(
            FIVE[:2],
            {**WITH_REST, "round_rest_seconds": 0},
            [90, 180],
            id="rounds with no round rest",
        ),
        pytest.param(
            FIVE[:1],
            {
                "rounds": 2,
                "work_seconds": 30,
                "round_rest_seconds": 20,
                "countdown_seconds": 10,
            },
            [50],
            id="one station",
        ),
        # The rest after round 2 belongs to round 2; the cool-down starts at 90 + 60 + 90 + 60.
        pytest.param(
            FIVE[:2],
            {**WITH_REST, "rounds": 2, "cooldown": COOLDOWN},
            [150, 300],
            id="cool-down after a rest",
        ),
        pytest.param(
            FIVE[:2],
            {**WITH_REST, "rounds": 2, "round_rest_seconds": 0, "cooldown": COOLDOWN},
            [90, 180],
            id="cool-down with no rest",
        ),
        pytest.param(
            FIVE[:2],
            {**WITH_REST, "countdown_seconds": 0},
            [150, 300],
            id="no countdown",
        ),
    ],
)
async def test_marks_in_the_current_session(
    make_app: MakeApp, stations: list[str], fields: dict[str, Any], marks: list[int]
) -> None:
    """The current session's `totals.marks` are where each round after the first and the cool-down start."""
    async with started(FrozenClock(WEDNESDAY_9), make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create(client, "Mærker", stations=stations, **fields)
        await start(client, program["id"], [thomas])
        view = await current(client)
    assert view["totals"]["marks"] == marks


async def test_marks_in_a_finished_session(make_app: MakeApp) -> None:
    """A finished session in `GET /sessions` carries the same `totals.marks`."""
    async with started(FrozenClock(WEDNESDAY_9), make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create(client, "Mærker", stations=FIVE[:2], **WITH_REST)
        await start(client, program["id"], [thomas])
        await ok(client, "end")
        history = (await client.get(SESSIONS)).json()
    [finished] = history["sessions"]
    assert finished["totals"]["marks"] == [150, 300]
