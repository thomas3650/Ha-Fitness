"""The timeline of a program (cool-down spec §4.2): every phase a session runs, built once and frozen into its plan.

This is the one place that knows the timing rules. The session engine, the totals and a program's length read what it
builds.
"""

from pydantic import BaseModel

from .schemas import Part, PhaseKind, ProgramDocument


class TimelineEntry(BaseModel):
    """One phase of a timeline.

    In the circuit, `round` and `interval` are the round and the station count from 1; the rest before the cool-down
    keeps the last round and station. In the cool-down `round` is 1 and `interval` the stretch's number from 1 (a
    change: the stretch it follows). `work` is a work entry's station offset (circuit) or stretch index from 0
    (cool-down), else None.
    """

    kind: PhaseKind
    part: Part
    round: int
    interval: int
    duration: int
    work: int | None


def build_timeline(document: ProgramDocument) -> list[TimelineEntry]:
    """Return the phases of a program, in order.

    1. The countdown, if set.
    2. Per round: per station a work, and a switch after it unless it is the round's last station.
    3. Between rounds: a rest, if set.
    4. With a cool-down: the rest after the last round, if set, in the circuit; then per stretch a work, and a change
       (a switch in the cool-down) between stretches, if set.
    """
    station_count = len(document.stations)
    rest = document.round_rest_seconds
    timeline: list[TimelineEntry] = []

    def add(
        kind: PhaseKind,
        part: Part,
        round_number: int,
        interval: int,
        duration: int,
        work: int | None = None,
    ) -> None:
        timeline.append(
            TimelineEntry(
                kind=kind,
                part=part,
                round=round_number,
                interval=interval,
                duration=duration,
                work=work,
            )
        )

    if document.countdown_seconds:
        add("countdown", "circuit", 1, 1, document.countdown_seconds)
    for round_number in range(1, document.rounds + 1):
        if round_number > 1 and rest:
            add("rest", "circuit", round_number - 1, station_count, rest)
        for interval in range(1, station_count + 1):
            add(
                "work",
                "circuit",
                round_number,
                interval,
                document.work_seconds,
                interval - 1,
            )
            if document.switch_seconds and interval < station_count:
                add(
                    "switch", "circuit", round_number, interval, document.switch_seconds
                )
    cooldown = document.cooldown
    if cooldown is not None:
        if rest:
            add("rest", "circuit", document.rounds, station_count, rest)
        for index in range(len(cooldown.stretches)):
            if index and cooldown.change_seconds:
                add("switch", "cooldown", 1, index, cooldown.change_seconds)
            add("work", "cooldown", 1, index + 1, cooldown.hold_seconds, index)
    return timeline
