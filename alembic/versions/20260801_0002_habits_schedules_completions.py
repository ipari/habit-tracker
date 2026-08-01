"""Create habits, schedule history, and completions.

Revision ID: 20260801_0002
Revises: 20260801_0001
Create Date: 2026-08-01
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260801_0002"
down_revision: str | None = "20260801_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "habits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("emoji", sa.String(length=32), nullable=False),
        sa.Column("background_preset", sa.String(length=32), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "habit_schedules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("habit_id", sa.Integer(), nullable=False),
        sa.Column("weekdays_mask", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "weekdays_mask >= 1 AND weekdays_mask <= 127",
            name="ck_habit_schedules_weekdays_mask",
        ),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_until > effective_from",
            name="ck_habit_schedules_valid_period",
        ),
        sa.ForeignKeyConstraint(["habit_id"], ["habits.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("habit_id", "effective_from", name="uq_habit_schedule_start"),
    )
    op.create_index(
        "ix_habit_schedules_lookup",
        "habit_schedules",
        ["habit_id", "effective_from", "effective_until"],
        unique=False,
    )
    op.create_table(
        "habit_completions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("habit_id", sa.Integer(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["habit_id"], ["habits.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("habit_id", "local_date", name="uq_habit_completion_date"),
    )
    op.create_index(
        "ix_habit_completions_date", "habit_completions", ["local_date"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_habit_completions_date", table_name="habit_completions")
    op.drop_table("habit_completions")
    op.drop_index("ix_habit_schedules_lookup", table_name="habit_schedules")
    op.drop_table("habit_schedules")
    op.drop_table("habits")
