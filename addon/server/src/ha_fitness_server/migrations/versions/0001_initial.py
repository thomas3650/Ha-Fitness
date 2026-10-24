"""The initial tables: programs, people, custom exercises and the change log.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the four tables."""
    op.create_table(
        "programs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("name_key", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_programs")),
        sqlite_autoincrement=True,
    )
    op.create_index(op.f("ix_programs_name_key"), "programs", ["name_key"], unique=True)
    op.create_table(
        "people",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("person_entity_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_people")),
        sa.UniqueConstraint(
            "person_entity_id", name=op.f("uq_people_person_entity_id")
        ),
        sqlite_autoincrement=True,
    )
    op.create_table(
        "custom_exercises",
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("name_key", sa.String(), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("number", name=op.f("pk_custom_exercises")),
    )
    op.create_index(
        op.f("ix_custom_exercises_name_key"),
        "custom_exercises",
        ["name_key"],
        unique=True,
    )
    op.create_table(
        "change_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("client", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_change_log")),
    )


def downgrade() -> None:
    """Drop the four tables."""
    op.drop_table("change_log")
    op.drop_index(op.f("ix_custom_exercises_name_key"), table_name="custom_exercises")
    op.drop_table("custom_exercises")
    op.drop_table("people")
    op.drop_index(op.f("ix_programs_name_key"), table_name="programs")
    op.drop_table("programs")
