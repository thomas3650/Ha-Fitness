"""Tests for the database, its migrations and the backup snapshot."""

import asyncio
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from ha_fitness_server import db
from ha_fitness_server.errors import DatabaseTooNew
import httpx
import pytest
from sqlalchemy import create_engine

from tests.conftest import MakeApp, running


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
