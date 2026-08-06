from app.db import Base


def test_multi_user_tables_are_in_metadata() -> None:
    assert set(Base.metadata.tables) == {
        "app_settings",
        "users",
        "invitations",
        "user_sessions",
        "password_reset_tokens",
        "habits",
        "habit_schedules",
        "habit_completions",
        "reminders",
        "push_subscriptions",
        "reminder_deliveries",
    }
