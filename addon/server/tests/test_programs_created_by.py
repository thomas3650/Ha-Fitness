"""Tests for who created a program (website spec §2.2.2), its backfill in migration 0006, and the program defaults."""

import json
from pathlib import Path
import sqlite3
from typing import Any

from alembic import command
from alembic.config import Config
from ha_fitness_server import db
import httpx
from sqlalchemy import create_engine

from tests.conftest import MakeApp, running
from tests.test_mcp import call, mcp_client

PROGRAMS = "/api/v1/programs"


def _program(name: str = "Onsdag", **fields: Any) -> dict[str, Any]:
    """Return a minimal valid program document with the given name."""
    return {
        "name": name,
        "weekdays": ["wed"],
        "stations": [{"exercise": "0001"}],
        **fields,
    }


async def test_rest_create_is_created_by_you(client: httpx.AsyncClient) -> None:
    """A program created over REST says "you", in the write's answer and on a later read."""
    response = await client.post(PROGRAMS, json=_program())
    assert response.status_code == 201, response.text
    assert response.json()["created_by"] == "you"
    program_id = response.json()["id"]
    assert (await client.get(f"{PROGRAMS}/{program_id}")).json()["created_by"] == "you"


async def test_mcp_create_is_created_by_claude(make_app: MakeApp) -> None:
    """A program created through MCP says "claude"; a later REST update keeps it."""
    app = make_app()
    async with mcp_client(app) as session:
        created = await call(session, "create_program", program=_program())
        assert created["created_by"] == "claude"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            program_id = created["id"]
            response = await client.put(
                f"{PROGRAMS}/{program_id}", json=_program(rounds=4)
            )
            assert response.status_code == 200, response.text
            assert response.json()["created_by"] == "claude"
            listed = (await client.get(PROGRAMS)).json()
            assert [program["created_by"] for program in listed] == ["claude"]


async def test_program_defaults(client: httpx.AsyncClient) -> None:
    """`GET /programs/defaults` returns the defaults a program gets for the fields it leaves out."""
    response = await client.get(f"{PROGRAMS}/defaults")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "rounds": 5,
        "work_seconds": 45,
        "switch_seconds": 15,
        "round_rest_seconds": 60,
        "countdown_seconds": 5,
    }


def _insert_program(connection: sqlite3.Connection, program_id: int, name: str) -> None:
    """Insert a program row as migration 0005 stored it."""
    connection.execute(
        "INSERT INTO programs (id, name, name_key, active, document, created_at, updated_at) "
        "VALUES (?, ?, ?, 1, ?, '2026-10-20 06:00:00', '2026-10-20 06:00:00')",
        (program_id, name, name.casefold(), json.dumps(_program(name, active=True))),
    )


def _insert_change(
    connection: sqlite3.Connection, client: str, action: str, target: str
) -> None:
    """Insert a change-log row."""
    connection.execute(
        "INSERT INTO change_log (at, client, action, target, summary) "
        "VALUES ('2026-10-20 06:00:00', ?, ?, ?, 'x')",
        (client, action, target),
    )


async def test_migration_0006_fills_created_by_from_the_change_log(
    make_app: MakeApp, tmp_path: Path
) -> None:
    """A database at 0005 migrates on the next start: `created_by` comes from each program's `program.created` row.

    An `mcp:` client is "claude", any other "you", no row null; only `program.created` counts, and the programs'
    training days keep their program.
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'ha_fitness.db'}")
    try:
        db.migrate(engine, "0005_session_feeling")
    finally:
        engine.dispose()
    # Raw-database setup: rows as the old version stored them.
    with sqlite3.connect(tmp_path / "ha_fitness.db") as connection:
        _insert_program(connection, 1, "Mandag")
        _insert_program(connection, 2, "Onsdag")
        _insert_program(connection, 3, "Fredag")
        _insert_program(connection, 12, "Lørdag")
        _insert_change(connection, "mcp:claude-code", "program.created", "program:1")
        _insert_change(
            connection, "rest:ha_fitness/1.0", "program.created", "program:2"
        )
        _insert_change(connection, "mcp:claude-code", "program.updated", "program:2")
        _insert_change(connection, "mcp:claude-code", "program.updated", "program:3")
        _insert_change(connection, "rest:curl", "program.created", "program:12")
        connection.execute(
            "INSERT INTO training_days (id, program_id, program_name, date, status, created_at, closed_at) "
            "VALUES (1, 1, 'Mandag', '2026-10-21', 'done', '2026-10-21 05:00:00', NULL)"
        )
    connection.close()
    async with running(make_app()) as client:
        created_by = {
            program_id: (await client.get(f"{PROGRAMS}/{program_id}")).json()[
                "created_by"
            ]
            for program_id in (1, 2, 3, 12)
        }
        days = await client.get(
            "/api/v1/training-days", params={"from": "2026-10-01", "to": "2026-10-31"}
        )
    assert created_by == {1: "claude", 2: "you", 3: None, 12: "you"}
    assert days.status_code == 200
    assert [day["program_id"] for day in days.json()] == [1]


def test_migration_0006_downgrade_keeps_training_days(tmp_path: Path) -> None:
    """Downgrading 0006 with the add-on's pragmas on drops `created_by` and `setup`, and keeps every day's program.

    A table rebuild would drop `programs`, and with `foreign_keys=ON` that sets every `training_days.program_id` null.
    """
    engine = db.open_database(tmp_path)
    try:
        # Raw-database setup and check: a downgrade has no public interface.
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO programs (id, name, name_key, active, document, created_at, updated_at, created_by) "
                "VALUES (1, 'Mandag', 'mandag', 1, '{}', '2026-10-20 06:00:00', '2026-10-20 06:00:00', 'you')"
            )
            connection.exec_driver_sql(
                "INSERT INTO training_days (id, program_id, program_name, date, status, created_at, closed_at) "
                "VALUES (1, 1, 'Mandag', '2026-10-21', 'done', '2026-10-21 05:00:00', NULL)"
            )
        config = Config()
        config.set_main_option("script_location", "ha_fitness_server:migrations")
        with engine.begin() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            config.attributes["connection"] = connection
            command.downgrade(config, "0005_session_feeling")
        with engine.connect() as connection:
            days = connection.exec_driver_sql(
                "SELECT id, program_id FROM training_days"
            ).all()
            columns = {
                row[1]
                for row in connection.exec_driver_sql("PRAGMA table_info(programs)")
            }
            tables = {
                row[0]
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
    finally:
        engine.dispose()
    assert [tuple(row) for row in days] == [(1, 1)]
    assert "created_by" not in columns
    assert "setup" not in tables
