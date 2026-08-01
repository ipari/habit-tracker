from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.calendar.service import build_calendar_view, month_dates, shift_month
from app.db.models import Habit, HabitCompletion, HabitSchedule
from app.domain.schedules import weekdays_to_mask
from app.habits.service import current_local_date
from tests.conftest import client_database, csrf_token, login

ALL_DAYS = weekdays_to_mask(list(range(7)))


def seed_daily_habit(client: TestClient, *, archived: bool = False) -> tuple[int, date]:
    database = client_database(client)
    with database.session_factory() as db:
        today = current_local_date(db)
        habit = Habit(
            name="매일 걷기",
            emoji="🚶",
            background_preset="forest",
            archived_at=datetime.now(UTC) if archived else None,
        )
        db.add(habit)
        db.flush()
        db.add(
            HabitSchedule(
                habit_id=habit.id,
                weekdays_mask=ALL_DAYS,
                effective_from=today - timedelta(days=40),
            )
        )
        db.commit()
        return habit.id, today


def test_month_math_handles_year_and_leap_boundaries() -> None:
    assert shift_month(date(2025, 12, 1), 1) == date(2026, 1, 1)
    assert shift_month(date(2026, 1, 1), -1) == date(2025, 12, 1)
    february = month_dates(date(2024, 2, 1))
    assert date(2024, 2, 29) in {day for week in february for day in week}
    assert all(len(week) == 7 for week in february)


def test_calendar_classifies_completion_and_missed_day(client: TestClient) -> None:
    habit_id, today = seed_daily_habit(client)
    with client_database(client).session_factory() as db:
        db.add(HabitCompletion(habit_id=habit_id, local_date=today))
        db.commit()
        view = build_calendar_view(
            db,
            date(today.year, today.month, 1),
            today,
            today,
        )

    days = {day.local_date: day for week in view.weeks for day in week}
    assert days[today].state == "complete"
    assert days[today].status_text == "예정 1개 중 1개 완료"
    assert days[today - timedelta(days=1)].state == "missed"
    assert view.habits[0].status_text == "예정일 달성"
    future = days[today + timedelta(days=1)]
    assert future.state == "future"
    assert future.status_text == "미래 날짜, 예정 1개"


def test_calendar_marks_unscheduled_completion_as_extra(client: TestClient) -> None:
    database = client_database(client)
    with database.session_factory() as db:
        today = current_local_date(db)
        non_today_weekday = (today.weekday() + 1) % 7
        habit = Habit(name="수영", emoji="🏊", background_preset="ocean")
        db.add(habit)
        db.flush()
        db.add(
            HabitSchedule(
                habit_id=habit.id,
                weekdays_mask=weekdays_to_mask([non_today_weekday]),
                effective_from=today - timedelta(days=7),
            )
        )
        db.add(HabitCompletion(habit_id=habit.id, local_date=today))
        db.commit()
        view = build_calendar_view(db, date(today.year, today.month, 1), today, today)

    assert view.habits[0].status_text == "추가 달성"
    selected_day = next(day for week in view.weeks for day in week if day.local_date == today)
    assert selected_day.extra_count == 1


def test_archived_habit_is_visible_before_archive_but_not_on_archive_day(
    client: TestClient,
) -> None:
    _habit_id, today = seed_daily_habit(client, archived=True)
    with client_database(client).session_factory() as db:
        month_start = date(today.year, today.month, 1)
        past_view = build_calendar_view(db, month_start, today - timedelta(days=1), today)
        today_view = build_calendar_view(db, month_start, today, today)
    assert len(past_view.habits) == 1
    assert today_view.habits == []


def test_calendar_page_and_past_completion_flow(client: TestClient) -> None:
    habit_id, today = seed_daily_habit(client)
    login(client)
    token = csrf_token(client)
    selected = today - timedelta(days=1)
    month = selected.strftime("%Y-%m")

    page = client.get(f"/calendar?month={month}&selected={selected.isoformat()}")
    assert page.status_code == 200
    assert "매일 걷기" in page.text
    assert 'class="status-label"' not in page.text

    response = client.post(
        f"/calendar/habits/{habit_id}/completions/{selected.isoformat()}",
        data={
            "completed": "true",
            "csrf_token": token,
            "month": month,
        },
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert 'class="status-label"' not in response.text
    with client_database(client).session_factory() as db:
        completion = db.scalar(
            select(HabitCompletion).where(
                HabitCompletion.habit_id == habit_id,
                HabitCompletion.local_date == selected,
            )
        )
        assert completion is not None


def test_future_schedule_uses_visual_indicator_without_repeated_text(
    client: TestClient,
) -> None:
    _habit_id, today = seed_daily_habit(client)
    login(client)
    future = today + timedelta(days=1)

    page = client.get(
        f"/calendar?month={future.strftime('%Y-%m')}&selected={future.isoformat()}"
    )

    assert page.status_code == 200
    assert "future-schedule-indicator" in page.text
    assert ">예정</span>" not in page.text


def test_calendar_rejects_future_completion(client: TestClient) -> None:
    habit_id, today = seed_daily_habit(client)
    login(client)
    token = csrf_token(client)
    future = today + timedelta(days=1)
    response = client.post(
        f"/calendar/habits/{habit_id}/completions/{future.isoformat()}",
        data={
            "completed": "true",
            "csrf_token": token,
            "month": future.strftime("%Y-%m"),
        },
    )
    assert response.status_code == 400


def test_calendar_requires_authentication_and_valid_month(client: TestClient) -> None:
    assert client.get("/calendar").status_code == 401
    login(client)
    assert client.get("/calendar?month=not-a-month").status_code == 400
