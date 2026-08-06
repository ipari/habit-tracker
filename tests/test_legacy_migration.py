from fastapi.testclient import TestClient
from sqlalchemy import select

from app.accounts.migrate_legacy_user import migrate_legacy_data
from app.auth.security import verify_password
from app.db.models import Habit, PushSubscription, User
from tests.conftest import client_database


def test_legacy_data_is_assigned_to_interactively_selected_member(
    client: TestClient,
) -> None:
    database = client_database(client)
    with database.session_factory() as db:
        habit = Habit(name="기존 습관", emoji="", background_preset="dawn")
        subscription = PushSubscription(
            endpoint="https://push.example.test/legacy",
            p256dh="p" * 65,
            auth="a" * 16,
            user_agent="legacy",
        )
        db.add_all([habit, subscription])
        db.flush()
        habit.user_id = None
        subscription.user_id = None
        db.commit()

        result = migrate_legacy_data(
            db,
            "Legacy@Example.com",
            "legacy password",
            "legacy password",
        )
        migrated = result.user
        assert migrated.normalized_email == "legacy@example.com"
        assert verify_password(migrated.password_hash, "legacy password")
        assert result.user_created is True
        assert result.habits_migrated == 1
        assert result.subscriptions_migrated == 1
        assert result.total_habits == 1
        assert result.user_habits == 1
        assert habit.user_id == migrated.id
        assert subscription.user_id == migrated.id
        assert db.scalar(
            select(User.id).where(User.normalized_email == "legacy@example.com")
        ) == migrated.id


def test_legacy_migration_can_be_retried_for_an_existing_member(
    client: TestClient,
) -> None:
    database = client_database(client)
    with database.session_factory() as db:
        first_result = migrate_legacy_data(
            db,
            "legacy@example.com",
            "legacy password",
            "legacy password",
        )
        orphaned_habit = Habit(
            name="뒤늦게 발견한 기존 습관",
            emoji="",
            background_preset="dawn",
        )
        db.add(orphaned_habit)
        db.flush()
        orphaned_habit.user_id = None
        db.commit()

        retry_result = migrate_legacy_data(
            db,
            "legacy@example.com",
            allow_existing_user=True,
        )

        assert retry_result.user.id == first_result.user.id
        assert retry_result.user_created is False
        assert retry_result.habits_migrated == 1
        assert retry_result.user_habits == 1
        assert orphaned_habit.user_id == first_result.user.id
