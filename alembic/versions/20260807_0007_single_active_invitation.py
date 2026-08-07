"""Limit each invitation creator to one active link.

Revision ID: 20260807_0007
Revises: 20260807_0006
Create Date: 2026-08-07
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260807_0007"
down_revision: str | None = "20260807_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE invitations
        SET is_active = 0,
            canceled_at = COALESCE(canceled_at, CURRENT_TIMESTAMP),
            updated_at = CURRENT_TIMESTAMP
        WHERE id IN (
            SELECT id
            FROM (
                SELECT id,
                       row_number() OVER (
                           PARTITION BY created_by_user_id
                           ORDER BY created_at DESC, id DESC
                       ) AS active_rank
                FROM invitations
                WHERE is_active = 1 AND created_by_user_id IS NOT NULL
            )
            WHERE active_rank > 1
        )
        """
    )
    op.execute(
        """
        UPDATE invitations
        SET is_active = 0,
            canceled_at = COALESCE(canceled_at, CURRENT_TIMESTAMP),
            updated_at = CURRENT_TIMESTAMP
        WHERE id IN (
            SELECT id
            FROM (
                SELECT id,
                       row_number() OVER (
                           ORDER BY created_at DESC, id DESC
                       ) AS active_rank
                FROM invitations
                WHERE is_active = 1 AND created_by_admin = 1
            )
            WHERE active_rank > 1
        )
        """
    )
    op.create_index(
        "uq_invitations_active_creator_user",
        "invitations",
        ["created_by_user_id"],
        unique=True,
        sqlite_where=sa.text("is_active = 1 AND created_by_user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_invitations_active_admin",
        "invitations",
        ["created_by_admin"],
        unique=True,
        sqlite_where=sa.text("is_active = 1 AND created_by_admin = 1"),
    )


def downgrade() -> None:
    op.drop_index("uq_invitations_active_admin", table_name="invitations")
    op.drop_index("uq_invitations_active_creator_user", table_name="invitations")
