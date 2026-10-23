"""Tests for the database, its migrations and the backup snapshot."""

import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from ha_fitness_server.errors import DatabaseTooNew
import pytest

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
    """A second start on the same data folder finds the database migrated."""
    async with running(make_app()) as client:
        assert (await client.get("/api/v1/health")).status_code == 200
    async with running(make_app()) as client:
        assert (await client.get("/api/v1/health")).status_code == 200


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
    """A missing database is restored from the backup snapshot before migrating."""
    async with running(make_app()):
        pass
    assert _run_snapshot(tmp_path).returncode == 0
    _delete_database(tmp_path)
    async with running(make_app()) as client:
        assert (await client.get("/api/v1/health")).status_code == 200
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


async def test_snapshot_command_runs(make_app: MakeApp, tmp_path: Path) -> None:
    """The snapshot command writes a consistent copy that holds the tables."""
    async with running(make_app()):
        pass
    result = _run_snapshot(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "programs" in _tables(tmp_path / "backup" / "snapshot.db")


def test_snapshot_without_database_exits_0(tmp_path: Path) -> None:
    """With no database yet the snapshot command does nothing and succeeds."""
    result = _run_snapshot(tmp_path)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "backup" / "snapshot.db").exists()
