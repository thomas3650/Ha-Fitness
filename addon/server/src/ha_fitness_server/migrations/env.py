"""Alembic's environment: migrates on the connection that `db.open_database` passes in.

There is no `alembic.ini` and no offline mode; the connection comes in `config.attributes["connection"]`.
"""

from alembic import context
from sqlalchemy.engine import Connection

from ha_fitness_server.models import Base

connection: Connection = context.config.attributes["connection"]
context.configure(
    connection=connection, target_metadata=Base.metadata, render_as_batch=True
)
with context.begin_transaction():
    context.run_migrations()
