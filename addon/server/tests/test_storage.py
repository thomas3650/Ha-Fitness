"""Tests for the database, its migrations and the backup snapshot."""

import asyncio
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from typing import Any

from alembic import command
from alembic.config import Config
from ha_fitness_server import db
from ha_fitness_server.errors import DatabaseTooNew
import httpx
import pytest
from sqlalchemy import create_engine

from tests.conftest import FrozenClock, MakeApp, running


def _set_revision(database: Path, revision: str) -> None:
    """Write a raw Alembic revision into a database file."""
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE alembic_version SET version_num = ?", (revision,))
    connection.close()


def _run_snapshot(data_dir: Path) -> subprocess.CompletedProcess[str]:
    """Run the backup snapshot command as the Supervisor's `backup_pre` does."""
    return subprocess.run(
        [sys.executable, "-m", "ha_fitness_server.snapshot"],
        env={**os.environ, "HA_FITNESS_DATA_DIR": str(data_dir)},
        capture_output=True,
        text=True,
        check=False,
    )


def _delete_database(data_dir: Path) -> None:
    """Remove the live database and its WAL files."""
    for path in data_dir.glob("ha_fitness.db*"):
        path.unlink()


PROGRAMS = "/api/v1/programs"
PROGRAM = {"name": "Onsdag", "weekdays": ["wed"], "stations": [{"exercise": "0001"}]}


async def _create_program(client: httpx.AsyncClient) -> None:
    """Create the test program; it must succeed."""
    response = await client.post(PROGRAMS, json=PROGRAM)
    assert response.status_code == 201, response.text


async def _program_names(client: httpx.AsyncClient) -> list[str]:
    """Return the names of the stored programs."""
    response = await client.get(PROGRAMS)
    assert response.status_code == 200
    return [body["program"]["name"] for body in response.json()]


def _snapshot_program_names(snapshot: Path) -> list[str]:
    """Return the program names in a snapshot file, read with `sqlite3`."""
    with sqlite3.connect(snapshot) as connection:
        rows = connection.execute("SELECT name FROM programs").fetchall()
    connection.close()
    return [name for (name,) in rows]


def _tables(database: Path) -> set[str]:
    """Return the table names of a database file."""
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    connection.close()
    return {name for (name,) in rows}


async def test_fresh_start_migrates_and_serves(
    make_app: MakeApp, tmp_path: Path
) -> None:
    """On an empty data folder the start creates the database and serves requests."""
    async with running(make_app()) as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert (tmp_path / "ha_fitness.db").exists()


async def test_second_start_is_a_noop(make_app: MakeApp) -> None:
    """A second start on the same data folder finds the database migrated and keeps the data."""
    async with running(make_app()) as client:
        assert (await client.get("/api/v1/health")).status_code == 200
        await _create_program(client)
    async with running(make_app()) as client:
        assert (await client.get("/api/v1/health")).status_code == 200
        assert await _program_names(client) == ["Onsdag"]


async def test_unknown_revision_stops_the_start(
    make_app: MakeApp, tmp_path: Path
) -> None:
    """A database at a revision this code doesn't know stops the start."""
    async with running(make_app()):
        pass
    _set_revision(tmp_path / "ha_fitness.db", "9999_future")
    app = make_app()
    with pytest.raises(DatabaseTooNew):
        async with app.router.lifespan_context(app):
            pass


async def test_start_restores_snapshot_when_database_missing(
    make_app: MakeApp, tmp_path: Path
) -> None:
    """A missing database is restored from the backup snapshot before migrating, with its programs."""
    async with running(make_app()) as client:
        await _create_program(client)
    assert _run_snapshot(tmp_path).returncode == 0
    assert _snapshot_program_names(tmp_path / "backup" / "snapshot.db") == ["Onsdag"]
    _delete_database(tmp_path)
    async with running(make_app()) as client:
        assert (await client.get("/api/v1/health")).status_code == 200
        assert await _program_names(client) == ["Onsdag"]
    assert (tmp_path / "ha_fitness.db").exists()


async def test_start_uses_the_snapshot_not_a_new_database(
    make_app: MakeApp, tmp_path: Path
) -> None:
    """The restored database is the snapshot: its unknown revision stops the start."""
    async with running(make_app()):
        pass
    assert _run_snapshot(tmp_path).returncode == 0
    _set_revision(tmp_path / "backup" / "snapshot.db", "9999_future")
    _delete_database(tmp_path)
    app = make_app()
    with pytest.raises(DatabaseTooNew):
        async with app.router.lifespan_context(app):
            pass


_LEAVE_A_WAL = """
import os, sqlite3, sys
connection = sqlite3.connect(sys.argv[1])
connection.execute("PRAGMA journal_mode=WAL")
connection.execute("PRAGMA wal_autocheckpoint=0")
connection.execute("UPDATE alembic_version SET version_num = '9999_future'")
connection.commit()
os._exit(0)
"""


def _leave_a_wal(database: Path) -> None:
    """Commit an unknown revision into the WAL only, and exit without a checkpoint, as a crashed run would."""
    subprocess.run([sys.executable, "-c", _LEAVE_A_WAL, str(database)], check=True)


async def test_restore_ignores_a_leftover_wal(
    make_app: MakeApp, tmp_path: Path
) -> None:
    """A WAL left behind by a crashed run is not replayed onto the restored snapshot."""
    async with running(make_app()):
        pass
    assert _run_snapshot(tmp_path).returncode == 0
    database = tmp_path / "ha_fitness.db"
    _leave_a_wal(database)
    assert (tmp_path / "ha_fitness.db-wal").exists()
    database.unlink()
    async with running(make_app()) as client:
        assert (await client.get("/api/v1/health")).status_code == 200


async def test_snapshot_command_runs(make_app: MakeApp, tmp_path: Path) -> None:
    """The snapshot command writes a consistent copy that holds the tables."""
    async with running(make_app()):
        pass
    result = _run_snapshot(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "programs" in _tables(tmp_path / "backup" / "snapshot.db")


async def test_snapshot_while_the_server_runs(
    make_app: MakeApp, tmp_path: Path
) -> None:
    """A snapshot taken while the server runs holds a program committed just before it."""
    async with running(make_app()) as client:
        await _create_program(client)
        result = await asyncio.to_thread(_run_snapshot, tmp_path)
        assert result.returncode == 0, result.stderr
        assert _snapshot_program_names(tmp_path / "backup" / "snapshot.db") == [
            "Onsdag"
        ]


def test_snapshot_without_database_exits_0(tmp_path: Path) -> None:
    """With no database yet the snapshot command does nothing and succeeds."""
    result = _run_snapshot(tmp_path)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "backup" / "snapshot.db").exists()


async def test_migration_0002_keeps_programs(make_app: MakeApp, tmp_path: Path) -> None:
    """A database at 0001 with a program migrates to head on the next start, and the program stays."""
    engine = create_engine(f"sqlite:///{tmp_path / 'ha_fitness.db'}")
    try:
        db.migrate(engine, "0001")
    finally:
        engine.dispose()
    # The second raw-database exception: setup only, a program as step 3 stored it.
    with sqlite3.connect(tmp_path / "ha_fitness.db") as connection:
        connection.execute(
            "INSERT INTO programs (name, name_key, active, document, created_at, updated_at) "
            "VALUES (?, ?, 1, ?, '2026-10-20 06:00:00', '2026-10-20 06:00:00')",
            ("Onsdag", "onsdag", json.dumps(PROGRAM | {"active": True})),
        )
    connection.close()
    async with running(make_app()) as client:
        assert await _program_names(client) == ["Onsdag"]
        response = await client.get(
            "/api/v1/training-days", params={"from": "2026-10-01", "to": "2026-10-31"}
        )
        assert response.status_code == 200


def test_migration_0005_downgrade_keeps_participants(tmp_path: Path) -> None:
    """Downgrading 0005 with the add-on's pragmas on drops `feeling` and keeps every session's participants.

    A table rebuild would drop `sessions`, and with `foreign_keys=ON` that deletes the participants on cascade.
    """
    engine = db.open_database(tmp_path)
    try:
        # Raw-database setup and check: a downgrade has no public interface.
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO sessions (id, plan, training_day_id, status, counted, phase_index, phase_started_at, "
                "paused_at, paused_seconds, last_tick_at, started_at, ended_at, rounds_completed, revision, "
                "feeling) VALUES (1, '{}', NULL, 'completed', 1, 8, '2026-10-07 07:01:10', NULL, 0, "
                "'2026-10-07 07:01:20', '2026-10-07 07:00:05', '2026-10-07 07:01:20', 2, 9, 'just_right')"
            )
            connection.exec_driver_sql(
                "INSERT INTO session_participants (session_id, position, person_id, name) "
                "VALUES (1, 0, 1, 'Thomas')"
            )
        config = Config()
        config.set_main_option("script_location", "ha_fitness_server:migrations")
        with engine.begin() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            config.attributes["connection"] = connection
            command.downgrade(config, "0004_people_added_at")
        with engine.connect() as connection:
            participants = connection.exec_driver_sql(
                "SELECT session_id, name FROM session_participants"
            ).all()
            columns = {
                row[1]
                for row in connection.exec_driver_sql("PRAGMA table_info(sessions)")
            }
    finally:
        engine.dispose()
    assert [tuple(row) for row in participants] == [(1, "Thomas")]
    assert "feeling" not in columns
    assert "revision" in columns


# A plan as 0006 stored it: 3 stations, 2 rounds, work 10, switch 5, rest 20, countdown 5.
PLAN_0006 = {
    "program_id": 1,
    "program_name": "Onsdag",
    "stations": [
        {"exercise_id": "0001", "name": "One"},
        {"exercise_id": "0002", "name": "Two"},
        {"exercise_id": "0003", "name": "Three"},
    ],
    "rounds": 2,
    "work_seconds": 10,
    "switch_seconds": 5,
    "round_rest_seconds": 20,
    "countdown_seconds": 5,
    "participants": [{"id": 1, "name": "Thomas"}],
    "music": None,
}
# The last tick of the running session at 0006; its rest (phase 7) started 5 s before it.
LAST_TICK = datetime(2026, 10, 28, 8, 0, 10, tzinfo=UTC)
TIMELINE_KEYS = (
    "timeline",
    "stretches",
    "cooldown_hold_seconds",
    "cooldown_change_seconds",
)


def _database_at_0006_with_a_running_session(data_dir: Path) -> None:
    """Build a database at 0006 holding a session running at phase 7, the rest under the rule before 0007."""
    engine = create_engine(f"sqlite:///{data_dir / 'ha_fitness.db'}")
    try:
        db.migrate(engine, "0006_setup_and_created_by")
    finally:
        engine.dispose()
    # Raw-database setup: a session as the add-on before 0007 stored it.
    with sqlite3.connect(data_dir / "ha_fitness.db") as connection:
        connection.execute(
            "INSERT INTO people (id, name, person_entity_id, position, added_at) "
            "VALUES (1, 'Thomas', 'person.thomas', 0, NULL)"
        )
        connection.execute(
            "INSERT INTO sessions (id, plan, training_day_id, status, counted, phase_index, phase_started_at, "
            "paused_at, paused_seconds, last_tick_at, started_at, ended_at, rounds_completed, revision) "
            "VALUES (1, ?, NULL, 'running', 0, 7, '2026-10-28 08:00:05', NULL, 0, '2026-10-28 08:00:10', "
            "'2026-10-28 07:59:40', NULL, 1, 8)",
            (json.dumps(PLAN_0006),),
        )
        connection.execute(
            "INSERT INTO session_participants (session_id, position, person_id, name) "
            "VALUES (1, 0, 1, 'Thomas')"
        )
    connection.close()


def _stored_plan(database: Path) -> dict[str, Any]:
    """Return the stored plan of session 1, read with `sqlite3`."""
    with sqlite3.connect(database) as connection:
        (plan,) = connection.execute(
            "SELECT plan FROM sessions WHERE id = 1"
        ).fetchone()
    connection.close()
    result: dict[str, Any] = json.loads(plan)
    return result


def test_0007_writes_old_rule_timeline(tmp_path: Path) -> None:
    """Migration 0007 gives a stored plan the timeline of the rule before it, no stretches and no cool-down times.

    A switch follows every work but the last of the last round; a rest sits between rounds.
    """
    _database_at_0006_with_a_running_session(tmp_path)
    db.open_database(tmp_path).dispose()
    # Raw-database check: no public interface shows the stored timeline until it drives the session.
    plan = _stored_plan(tmp_path / "ha_fitness.db")
    timeline = plan["timeline"]
    assert len(timeline) == 13
    assert timeline[0] == {
        "kind": "countdown",
        "part": "circuit",
        "round": 1,
        "interval": 1,
        "duration": 5,
        "work": None,
    }
    assert timeline[5] == {
        "kind": "work",
        "part": "circuit",
        "round": 1,
        "interval": 3,
        "duration": 10,
        "work": 2,
    }
    assert timeline[6] == {
        "kind": "switch",
        "part": "circuit",
        "round": 1,
        "interval": 3,
        "duration": 5,
        "work": None,
    }
    assert timeline[7] == {
        "kind": "rest",
        "part": "circuit",
        "round": 1,
        "interval": 3,
        "duration": 20,
        "work": None,
    }
    assert [entry["kind"] for entry in timeline[8:]] == [
        "work",
        "switch",
        "work",
        "switch",
        "work",
    ]
    assert timeline[12]["round"] == 2
    assert timeline[12]["work"] == 2
    assert plan["stretches"] == []
    assert plan["cooldown_hold_seconds"] == 0
    assert plan["cooldown_change_seconds"] == 0
    assert {key: plan[key] for key in PLAN_0006} == PLAN_0006


async def test_0007_running_session_keeps_its_phase(
    make_app: MakeApp, tmp_path: Path
) -> None:
    """A session running at 0006 is at the same phase after 0007: phase 7 stays the rest after round 1."""
    _database_at_0006_with_a_running_session(tmp_path)
    clock = FrozenClock(LAST_TICK + timedelta(minutes=5))
    async with running(make_app(clock=clock)) as client:
        response = await client.get("/api/v1/session")
    assert response.status_code == 200
    phase = response.json()["phase"]
    assert (phase["index"], phase["kind"], phase["round"], phase["interval"]) == (
        7,
        "rest",
        1,
        3,
    )


def test_0007_downgrade_drops_the_keys(tmp_path: Path) -> None:
    """Downgrading 0007 removes the timeline, the stretches and both cool-down times, and keeps the rest of the plan."""
    _database_at_0006_with_a_running_session(tmp_path)
    engine = db.open_database(tmp_path)
    try:
        # Raw-database check: a downgrade has no public interface.
        assert "timeline" in _stored_plan(tmp_path / "ha_fitness.db")
        config = Config()
        config.set_main_option("script_location", "ha_fitness_server:migrations")
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "0006_setup_and_created_by")
    finally:
        engine.dispose()
    plan = _stored_plan(tmp_path / "ha_fitness.db")
    assert not set(TIMELINE_KEYS) & set(plan)
    assert plan == PLAN_0006
