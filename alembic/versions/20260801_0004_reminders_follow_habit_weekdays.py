"""Make reminder weekdays always follow the habit schedule.

Revision ID: 20260801_0004
Revises: 20260801_0003
Create Date: 2026-08-01
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260801_0004"
down_revision: str | None = "20260801_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("reminders") as batch_op:
        batch_op.drop_column("use_habit_weekdays")


def downgrade() -> None:
    with op.batch_alter_table("reminders") as batch_op:
        batch_op.add_column(
            sa.Column(
                "use_habit_weekdays",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
