"""Create singleton application settings.

Revision ID: 20260801_0001
Revises:
Create Date: 2026-08-01
"""
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "20260801_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_app_settings_singleton"),
        sa.PrimaryKeyConstraint("id"),
    )
    now = datetime.now(UTC)
    op.bulk_insert(
        sa.table(
            "app_settings",
            sa.column("id", sa.Integer()),
            sa.column("timezone", sa.String()),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        ),
        [{"id": 1, "timezone": "Asia/Seoul", "created_at": now, "updated_at": now}],
    )


def downgrade() -> None:
    op.drop_table("app_settings")
