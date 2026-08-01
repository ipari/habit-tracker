"""Create per-habit reminder settings.

Revision ID: 20260801_0003
Revises: 20260801_0002
Create Date: 2026-08-01
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260801_0003"
down_revision: str | None = "20260801_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reminders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("habit_id", sa.Integer(), nullable=False),
        sa.Column("weekdays_mask", sa.Integer(), nullable=False),
        sa.Column("local_time", sa.Time(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("use_habit_weekdays", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "weekdays_mask >= 1 AND weekdays_mask <= 127",
            name="ck_reminders_weekdays_mask",
        ),
        sa.ForeignKeyConstraint(["habit_id"], ["habits.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("habit_id"),
    )


def downgrade() -> None:
    op.drop_table("reminders")
