"""Allow completed reminder occurrences to be skipped.

Revision ID: 20260823_0008
Revises: 20260807_0007
Create Date: 2026-08-23
"""
from collections.abc import Sequence

from alembic import op

revision: str = "20260823_0008"
down_revision: str | None = "20260807_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("reminder_deliveries", recreate="always") as batch_op:
        batch_op.drop_constraint(
            "ck_reminder_deliveries_status", type_="check"
        )
        batch_op.create_check_constraint(
            "ck_reminder_deliveries_status",
            "status IN ('pending', 'sent', 'failed', 'skipped')",
        )


def downgrade() -> None:
    op.execute(
        """
        UPDATE reminder_deliveries
        SET status = 'failed',
            error = 'Skipped because the habit was completed'
        WHERE status = 'skipped'
        """
    )
    with op.batch_alter_table("reminder_deliveries", recreate="always") as batch_op:
        batch_op.drop_constraint(
            "ck_reminder_deliveries_status", type_="check"
        )
        batch_op.create_check_constraint(
            "ck_reminder_deliveries_status",
            "status IN ('pending', 'sent', 'failed')",
        )
