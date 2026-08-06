"""Add invite-only users, database sessions, and data ownership.

Revision ID: 20260807_0006
Revises: 20260801_0005
Create Date: 2026-08-07
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260807_0006"
down_revision: str | None = "20260801_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRESERVED_TABLES = (
    "habits",
    "habit_schedules",
    "habit_completions",
    "reminders",
    "push_subscriptions",
    "reminder_deliveries",
)


def upgrade() -> None:
    connection = op.get_bind()
    counts_before = {
        table: connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar_one()
        for table in PRESERVED_TABLES
    }
    op.create_table(
        "invitations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=12), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_by_admin", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(code) = 12", name="ck_invitations_code_length"),
        sa.CheckConstraint(
            "created_by_admin = 1 OR created_by_user_id IS NOT NULL OR is_active = 0",
            name="ck_invitations_creator",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("normalized_email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("invitation_id", sa.Integer(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["invitation_id"], ["invitations.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_email"),
    )
    with op.batch_alter_table("invitations") as batch_op:
        batch_op.create_foreign_key(
            "fk_invitations_created_by_user_id_users",
            "users",
            ["created_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("credential_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('admin', 'member')", name="ck_user_sessions_role"
        ),
        sa.CheckConstraint(
            "(role = 'admin' AND user_id IS NULL) OR "
            "(role = 'member' AND user_id IS NOT NULL)",
            name="ck_user_sessions_subject",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    with op.batch_alter_table("app_settings") as batch_op:
        batch_op.drop_constraint("ck_app_settings_singleton", type_="check")
        batch_op.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_app_settings_user_id_users", "users", ["user_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.create_unique_constraint("uq_app_settings_user_id", ["user_id"])
    # These parent tables already have ON DELETE CASCADE children. SQLite batch mode
    # recreates a table by dropping the original, which would delete schedules,
    # completions, reminders, and delivery history while foreign keys are enabled.
    # SQLite supports adding a nullable REFERENCES column natively, so keep the
    # existing parent rows in place and preserve every child row.
    op.execute(
        "ALTER TABLE habits ADD COLUMN user_id INTEGER "
        "REFERENCES users(id) ON DELETE CASCADE"
    )
    op.create_index("ix_habits_user_id", "habits", ["user_id"], unique=False)
    op.execute(
        "ALTER TABLE push_subscriptions ADD COLUMN user_id INTEGER "
        "REFERENCES users(id) ON DELETE CASCADE"
    )
    op.create_index(
        "ix_push_subscriptions_user_id",
        "push_subscriptions",
        ["user_id"],
        unique=False,
    )
    counts_after = {
        table: connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar_one()
        for table in PRESERVED_TABLES
    }
    if counts_after != counts_before:
        raise RuntimeError(
            "Multi-user migration changed protected row counts: "
            f"before={counts_before}, after={counts_after}"
        )
    foreign_key_violations = connection.exec_driver_sql(
        "PRAGMA foreign_key_check"
    ).fetchall()
    if foreign_key_violations:
        raise RuntimeError(
            "Multi-user migration introduced foreign key violations: "
            f"{foreign_key_violations}"
        )


def downgrade() -> None:
    with op.batch_alter_table("push_subscriptions") as batch_op:
        batch_op.drop_index("ix_push_subscriptions_user_id")
        batch_op.drop_constraint("fk_push_subscriptions_user_id_users", type_="foreignkey")
        batch_op.drop_column("user_id")
    with op.batch_alter_table("habits") as batch_op:
        batch_op.drop_index("ix_habits_user_id")
        batch_op.drop_constraint("fk_habits_user_id_users", type_="foreignkey")
        batch_op.drop_column("user_id")
    with op.batch_alter_table("app_settings") as batch_op:
        batch_op.drop_constraint("uq_app_settings_user_id", type_="unique")
        batch_op.drop_constraint("fk_app_settings_user_id_users", type_="foreignkey")
        batch_op.drop_column("user_id")
        batch_op.create_check_constraint("ck_app_settings_singleton", "id = 1")
    op.drop_table("password_reset_tokens")
    op.drop_table("user_sessions")
    with op.batch_alter_table("invitations") as batch_op:
        batch_op.drop_constraint(
            "fk_invitations_created_by_user_id_users", type_="foreignkey"
        )
    op.drop_table("users")
    op.drop_table("invitations")
