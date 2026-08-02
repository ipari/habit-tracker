from datetime import UTC, date, datetime, time

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import AppSettings, Habit, HabitSchedule, Reminder
from app.domain.schedules import ScheduleWindow, schedule_for_date, weekdays_to_mask
from app.habits.service import (
    current_local_date,
    pause_schedule,
    restart_habit,
    schedule_windows,
    update_schedule,
)
from tests.conftest import client_database


def test_same_day_schedule_edit_replaces_row(client: TestClient) -> None:
    with client_database(client).session_factory() as db:
        habit = Habit(name="운동", emoji="🏃", background_preset="dawn")
        db.add(habit)
        db.flush()
        update_schedule(db, habit, weekdays_to_mask([0]), date(2026, 8, 1))
        update_schedule(db, habit, weekdays_to_mask([1, 3]), date(2026, 8, 1))
        db.commit()

        schedules = db.scalars(
            select(HabitSchedule).where(HabitSchedule.habit_id == habit.id)
        ).all()
        assert len(schedules) == 1
        assert schedules[0].weekdays_mask == weekdays_to_mask([1, 3])


def test_later_schedule_edit_closes_previous_period(client: TestClient) -> None:
    with client_database(client).session_factory() as db:
        habit = Habit(name="독서", emoji="📚", background_preset="forest")
        db.add(habit)
        db.flush()
        first = update_schedule(db, habit, weekdays_to_mask([0, 2, 4]), date(2026, 8, 1))
        second = update_schedule(db, habit, weekdays_to_mask([1, 3, 5]), date(2026, 8, 6))
        db.commit()

        assert first.effective_until == date(2026, 8, 6)
        assert second.effective_from == date(2026, 8, 6)


def test_overlapping_schedule_windows_are_rejected() -> None:
    schedules = [
        ScheduleWindow(1, date(2026, 1, 1)),
        ScheduleWindow(2, date(2026, 1, 2)),
    ]
    try:
        schedule_for_date(schedules, date(2026, 1, 3))
    except ValueError as exc:
        assert "Overlapping" in str(exc)
    else:
        raise AssertionError("Expected overlapping schedules to be rejected")


def test_current_date_uses_app_iana_timezone(client: TestClient) -> None:
    with client_database(client).session_factory() as db:
        settings = db.get(AppSettings, 1)
        assert settings is not None
        settings.timezone = "Asia/Seoul"
        db.commit()
        assert current_local_date(db, datetime(2026, 8, 1, 16, 0, tzinfo=UTC)) == date(
            2026, 8, 2
        )


def test_archive_gap_is_unscheduled_and_restart_reuses_last_weekdays(
    client: TestClient,
) -> None:
    with client_database(client).session_factory() as db:
        habit = Habit(name="달리기", emoji="🏃", background_preset="dawn")
        db.add(habit)
        db.flush()
        weekdays_mask = weekdays_to_mask([0, 2, 4])
        first = update_schedule(db, habit, weekdays_mask, date(2026, 8, 1))
        reminder = Reminder(
            habit=habit,
            weekdays_mask=weekdays_mask,
            local_time=time(7, 30),
            timezone="Asia/Seoul",
            is_enabled=True,
        )
        db.add(reminder)
        habit.archived_at = datetime(2026, 8, 1, 3, tzinfo=UTC)
        pause_schedule(db, habit, date(2026, 8, 1))
        reminder.is_enabled = False

        restart_habit(db, habit, date(2026, 8, 5))
        db.commit()

        windows = schedule_windows(db, habit.id)
        assert first.effective_until == date(2026, 8, 2)
        assert schedule_for_date(windows, date(2026, 8, 3)) is None
        restarted = schedule_for_date(windows, date(2026, 8, 5))
        assert restarted is not None
        assert restarted.weekdays_mask == weekdays_mask
        assert habit.archived_at is None
        assert reminder.is_enabled is True
        assert reminder.local_time == time(7, 30)
