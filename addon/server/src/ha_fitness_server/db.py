"""The SQLite database: opening it, migrating it and sessions on it (spec §10)."""

from collections.abc import Iterator
from contextlib import contextmanager
import logging
from pathlib import Path
import shutil

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.orm import Session
from sqlalchemy.pool import ConnectionPoolEntry

from .errors import DatabaseTooNew

_LOGGER = logging.getLogger(__name__)

DATABASE_NAME = "ha_fitness.db"
SNAPSHOT_PATH = Path("backup") / "snapshot.db"


def open_database(data_dir: Path) -> Engine:
    """Open `<data_dir>/ha_fitness.db`, restoring the backup snapshot if it is missing, and migrate it to head."""
    database = data_dir / DATABASE_NAME
    _restore_snapshot(data_dir, database)
    engine = create_engine(f"sqlite:///{database}")
    event.listen(engine, "connect", _set_pragmas)
    try:
        _migrate(engine)
    except BaseException:
        engine.dispose()
        raise
    return engine


@contextmanager
def session(engine: Engine) -> Iterator[Session]:
    """Yield a session in a transaction that commits on success and rolls back on error."""
    with Session(engine, expire_on_commit=False) as db_session, db_session.begin():
        yield db_session


def _set_pragmas(
    dbapi_connection: DBAPIConnection, _record: ConnectionPoolEntry
) -> None:
    """Turn on WAL mode and foreign keys on every new connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _restore_snapshot(data_dir: Path, database: Path) -> None:
    """Copy `backup/snapshot.db` into place when the database is missing (after a restore)."""
    snapshot = data_dir / SNAPSHOT_PATH
    if database.exists() or not snapshot.exists():
        return
    _LOGGER.info("The database is missing; restoring it from %s", snapshot)
    # A WAL left by a crashed run belongs to the lost database; SQLite would replay it onto the snapshot.
    for suffix in ("-wal", "-shm"):
        leftover = database.with_name(f"{DATABASE_NAME}{suffix}")
        if leftover.exists():
            _LOGGER.warning(
                "Removing %s, left over from the missing database", leftover
            )
        leftover.unlink(missing_ok=True)
    partial = database.with_name(f"{DATABASE_NAME}.restoring")
    shutil.copyfile(snapshot, partial)
    partial.replace(database)


def _migrate(engine: Engine) -> None:
    """Run the migrations to head; refuse a revision this code doesn't know."""
    config = Config()
    config.set_main_option("script_location", "ha_fitness_server:migrations")
    known = {
        script.revision
        for script in ScriptDirectory.from_config(config).walk_revisions()
    }
    with engine.begin() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
        if current is not None and current not in known:
            _LOGGER.error(
                "The database is at revision %s, which this version of HA Fitness doesn't know; "
                "update the add-on or restore an older backup",
                current,
            )
            raise DatabaseTooNew(f"unknown database revision {current}")
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
