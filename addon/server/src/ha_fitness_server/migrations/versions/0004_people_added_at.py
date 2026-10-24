"""When each person was added (stats spec §3.1).

Revision ID: 0004_people_added_at
Revises: 0003_sessions
Create Date: 2026-10-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0004_people_added_at"
down_revision: str | Sequence[str] | None = "0003_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable `people.added_at`; existing people stay null, which counts from the start."""
    with op.batch_alter_table("people") as batch_op:
        batch_op.add_column(sa.Column("added_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Drop `people.added_at`; the rebuilt table keeps AUTOINCREMENT, so ids are still never reused."""
    with op.batch_alter_table(
        "people", table_kwargs={"sqlite_autoincrement": True}
    ) as batch_op:
        batch_op.drop_column("added_at")
