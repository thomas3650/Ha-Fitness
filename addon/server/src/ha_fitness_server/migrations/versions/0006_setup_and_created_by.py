"""Who created each program, and the household setup (website spec §2.2.2, §2.4).

Revision ID: 0006_setup_and_created_by
Revises: 0005_session_feeling
Create Date: 2026-10-26
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0006_setup_and_created_by"
down_revision: str | Sequence[str] | None = "0005_session_feeling"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_SETUP = {
    "equipment": ["body weight"],
    "favourite_playlists": [],
    "default_speaker": None,
}


def upgrade() -> None:
    """Add `programs.created_by`, filled from each program's `program.created` row, and the `setup` table.

    The column is added natively, with no batch rebuild: with `foreign_keys=ON` a rebuild's `DROP TABLE programs`
    would set every `training_days.program_id` null. A program without a `program.created` row stays null.
    """
    op.add_column("programs", sa.Column("created_by", sa.String(16), nullable=True))
    op.execute(
        "UPDATE programs SET created_by = ("
        "SELECT CASE WHEN substr(change_log.client, 1, 4) = 'mcp:' THEN 'claude' ELSE 'you' END "
        "FROM change_log WHERE change_log.action = 'program.created' "
        "AND change_log.target = 'program:' || programs.id "
        "ORDER BY change_log.id LIMIT 1)"
    )
    setup = op.create_table(
        "setup",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_setup")),
    )
    op.bulk_insert(setup, [{"id": 1, "document": _DEFAULT_SETUP}])


def downgrade() -> None:
    """Drop `setup`, and `programs.created_by` with a native `ALTER TABLE … DROP COLUMN` (SQLite 3.35 or later).

    No batch rebuild, as in 0005: with `foreign_keys=ON` its `DROP TABLE programs` would set every training day's
    `program_id` null.
    """
    op.drop_table("setup")
    op.execute("ALTER TABLE programs DROP COLUMN created_by")
