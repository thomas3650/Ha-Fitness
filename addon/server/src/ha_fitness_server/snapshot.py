"""The backup snapshot: `python -m ha_fitness_server.snapshot`, run by the Supervisor's `backup_pre` (spec §10).

It writes a consistent copy of the live WAL database with `VACUUM INTO` to a temporary name and renames it to
`backup/snapshot.db`, so a failed run never leaves a half snapshot.
"""

import logging
from pathlib import Path
import sqlite3

from .db import DATABASE_NAME, SNAPSHOT_PATH
from .settings import Settings

_LOGGER = logging.getLogger(__name__)


def write_snapshot(data_dir: Path) -> Path | None:
    """Write `<data_dir>/backup/snapshot.db` and return its path; without a database do nothing and return None."""
    database = data_dir / DATABASE_NAME
    if not database.exists():
        return None
    snapshot = data_dir / SNAPSHOT_PATH
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    partial = snapshot.with_name(f"{snapshot.name}.partial")
    partial.unlink(missing_ok=True)
    connection = sqlite3.connect(database)
    try:
        connection.execute("VACUUM INTO ?", (str(partial),))
    finally:
        connection.close()
    partial.replace(snapshot)
    return snapshot


def main() -> None:
    """Write the snapshot for the data folder of the environment's settings."""
    logging.basicConfig(level=logging.INFO)
    snapshot = write_snapshot(Settings.from_env().data_dir)
    if snapshot is None:
        _LOGGER.info("No database yet; no snapshot written")
    else:
        _LOGGER.info("Snapshot written to %s", snapshot)


if __name__ == "__main__":
    main()
