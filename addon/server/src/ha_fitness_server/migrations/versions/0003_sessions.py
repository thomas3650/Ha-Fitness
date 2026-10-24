"""Sessions, their participants and the app's state (step 5 spec §3.2, §3.4).

Revision ID: 0003_sessions
Revises: 0002_training_days
Create Date: 2026-10-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0003_sessions"
down_revision: str | Sequence[str] | None = "0002_training_days"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = ("running", "paused", "completed", "ended")


def upgrade() -> None:
    """Create `sessions`, `session_participants` and `app_state`, with the app's one row."""
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("training_day_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(*_STATUSES, name="sessionstatus", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("counted", sa.Boolean(), nullable=False),
        sa.Column("phase_index", sa.Integer(), nullable=False),
        sa.Column("phase_started_at", sa.DateTime(), nullable=False),
        sa.Column("paused_at", sa.DateTime(), nullable=True),
        sa.Column("paused_seconds", sa.Float(), nullable=False),
        sa.Column("last_tick_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("rounds_completed", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["training_day_id"],
            ["training_days.id"],
            name=op.f("fk_sessions_training_day_id_training_days"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        # An id is never reused: history and the cards refer to sessions by id.
        sqlite_autoincrement=True,
    )
    op.create_index(op.f("ix_sessions_status"), "sessions", ["status"])
    op.create_table(
        "session_participants",
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name=op.f("fk_session_participants_session_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "session_id", "position", name=op.f("pk_session_participants")
        ),
    )
    app_state = op.create_table(
        "app_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("counting_from", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_state")),
    )
    op.bulk_insert(app_state, [{"id": 1, "counting_from": None}])


def downgrade() -> None:
    """Drop the three tables."""
    op.drop_table("app_state")
    op.drop_table("session_participants")
    op.drop_index(op.f("ix_sessions_status"), table_name="sessions")
    op.drop_table("sessions")
