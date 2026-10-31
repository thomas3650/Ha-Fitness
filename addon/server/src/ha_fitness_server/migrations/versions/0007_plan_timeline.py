"""Every stored session plan gets its timeline (cool-down spec §4.3).

Revision ID: 0007_plan_timeline
Revises: 0006_setup_and_created_by
Create Date: 2026-10-31
"""

from collections.abc import Callable, Sequence
import json
from typing import Any

from alembic import op
import sqlalchemy as sa

revision: str = "0007_plan_timeline"
down_revision: str | Sequence[str] | None = "0006_setup_and_created_by"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEYS = ("timeline", "stretches", "cooldown_hold_seconds", "cooldown_change_seconds")


def _timeline(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the timeline of a plan under the phase rule before 0007, frozen here.

    A countdown first when set; a switch after every work but the last of the last round; a rest between rounds.
    Every entry is in the circuit; `work` is the station offset of a work entry, else null.
    """
    station_count = len(plan["stations"])
    rounds = plan["rounds"]
    timeline: list[dict[str, Any]] = []

    def add(
        kind: str, round_number: int, interval: int, duration: int, work: int | None
    ) -> None:
        timeline.append(
            {
                "kind": kind,
                "part": "circuit",
                "round": round_number,
                "interval": interval,
                "duration": duration,
                "work": work,
            }
        )

    if plan["countdown_seconds"]:
        add("countdown", 1, 1, plan["countdown_seconds"], None)
    for round_number in range(1, rounds + 1):
        last_round = round_number == rounds
        for interval in range(1, station_count + 1):
            add("work", round_number, interval, plan["work_seconds"], interval - 1)
            last = last_round and interval == station_count
            if plan["switch_seconds"] and not last:
                add("switch", round_number, interval, plan["switch_seconds"], None)
        if plan["round_rest_seconds"] and not last_round:
            add("rest", round_number, station_count, plan["round_rest_seconds"], None)
    return timeline


def _rewrite(change: Callable[[dict[str, Any]], None]) -> None:
    """Load every stored plan, apply `change` to it, and store it again."""
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, plan FROM sessions")).all()
    for session_id, stored in rows:
        plan: dict[str, Any] = json.loads(stored)
        change(plan)
        connection.execute(
            sa.text("UPDATE sessions SET plan = :plan WHERE id = :id"),
            {"plan": json.dumps(plan), "id": session_id},
        )


def upgrade() -> None:
    """Write into every stored plan its timeline under the rule before 0007, no stretches and no cool-down times.

    The plan is a JSON column, so no table changes; no batch rebuild, which with `foreign_keys=ON` would delete every
    participant on cascade.
    """

    def add_timeline(plan: dict[str, Any]) -> None:
        plan["timeline"] = _timeline(plan)
        plan["stretches"] = []
        plan["cooldown_hold_seconds"] = 0
        plan["cooldown_change_seconds"] = 0

    _rewrite(add_timeline)


def downgrade() -> None:
    """Remove the timeline, the stretches and both cool-down times from every stored plan; a missing key is fine."""

    def drop_timeline(plan: dict[str, Any]) -> None:
        for key in _KEYS:
            plan.pop(key, None)

    _rewrite(drop_timeline)
