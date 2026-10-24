"""Training days and the scheduler's state (step 4 spec §3.1 and §3.3).

Revision ID: 0002_training_days
Revises: 0001_initial
Create Date: 2026-10-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002_training_days"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = ("open", "done", "missed", "skipped")


def upgrade() -> None:
    """Create `training_days` and `scheduler_state`, with the scheduler's one row."""
    op.create_table(
        "training_days",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("program_id", sa.Integer(), nullable=True),
        sa.Column("program_name", sa.String(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(*_STATUSES, name="trainingdaystatus", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["programs.id"],
            name=op.f("fk_training_days_program_id_programs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_training_days")),
        sa.UniqueConstraint(
            "program_id", "date", name=op.f("uq_training_days_program_id")
        ),
        # An id is never reused after a delete: the card and the service skip by id.
        sqlite_autoincrement=True,
    )
    op.create_index(op.f("ix_training_days_date"), "training_days", ["date"])
    scheduler_state = op.create_table(
        "scheduler_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("last_date", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduler_state")),
    )
    op.bulk_insert(scheduler_state, [{"id": 1, "last_date": None}])


def downgrade() -> None:
    """Drop the two tables."""
    op.drop_table("scheduler_state")
    op.drop_index(op.f("ix_training_days_date"), table_name="training_days")
    op.drop_table("training_days")
