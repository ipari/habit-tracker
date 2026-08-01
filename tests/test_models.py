from app.db import Base


def test_authentication_tables_are_not_in_metadata() -> None:
    assert "users" not in Base.metadata.tables
    assert "auth_sessions" not in Base.metadata.tables
    assert set(Base.metadata.tables) == {
        "app_settings",
        "habits",
        "habit_schedules",
        "habit_completions",
        "reminders",
        "push_subscriptions",
        "reminder_deliveries",
    }
