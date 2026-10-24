"""How a workout felt (UI refresh spec §3.3).

Revision ID: 0005_session_feeling
Revises: 0004_people_added_at
Create Date: 2026-10-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0005_session_feeling"
down_revision: str | Sequence[str] | None = "0004_people_added_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable `sessions.feeling`; existing sessions stay null, unrated."""
    with op.batch_alter_table("sessions") as batch_op:
        batch_op.add_column(sa.Column("feeling", sa.String(16), nullable=True))


def downgrade() -> None:
    """Drop `sessions.feeling`; the rebuilt table keeps AUTOINCREMENT, so ids are still never reused."""
    with op.batch_alter_table(
        "sessions", table_kwargs={"sqlite_autoincrement": True}
    ) as batch_op:
        batch_op.drop_column("feeling")
