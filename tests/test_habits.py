from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import Habit, HabitCompletion, HabitSchedule, Reminder
from app.habits.service import current_local_date
from tests.conftest import client_database, csrf_token, login


def create_habit(client: TestClient, weekdays: list[int] | None = None) -> int:
    login(client)
    token = csrf_token(client)
    database = client_database(client)
    with database.session_factory() as db:
        today = current_local_date(db)
    form_data: dict[str, Any] = {
        "name": "물 마시기",
        "emoji": "💧",
        "background_preset": "ocean",
        "weekdays": weekdays or [today.weekday()],
        "csrf_token": token,
    }
    response = client.post(
        "/habits",
        data=form_data,
        follow_redirects=False,
    )
    assert response.status_code == 303
    with database.session_factory() as db:
        habit_id = db.scalar(select(Habit.id).where(Habit.name == "물 마시기"))
        assert habit_id is not None
        return habit_id


def test_create_habit_and_show_it_on_today(client: TestClient) -> None:
    habit_id = create_habit(client)
    today_page = client.get("/today")
    assert today_page.status_code == 200
    assert "물 마시기" in today_page.text
    assert "연속 0회" in today_page.text

    with client_database(client).session_factory() as db:
        schedule = db.scalar(select(HabitSchedule).where(HabitSchedule.habit_id == habit_id))
        assert schedule is not None
        assert schedule.effective_from == current_local_date(db)


def test_completion_set_and_unset_are_idempotent(client: TestClient) -> None:
    habit_id = create_habit(client)
    token = csrf_token(client)
    database = client_database(client)
    with database.session_factory() as db:
        today = current_local_date(db)
    url = f"/habits/{habit_id}/completions/{today.isoformat()}"

    for _ in range(2):
        response = client.post(
            url,
            data={"completed": "true", "csrf_token": token},
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        assert "연속 1회" in response.text
    with database.session_factory() as db:
        count = db.scalar(select(func.count()).select_from(HabitCompletion))
        assert count == 1

    for _ in range(2):
        assert client.post(url, data={"completed": "false", "csrf_token": token}).status_code == 200
    with database.session_factory() as db:
        count = db.scalar(select(func.count()).select_from(HabitCompletion))
        assert count == 0


def test_future_completion_is_rejected(client: TestClient) -> None:
    habit_id = create_habit(client)
    token = csrf_token(client)
    with client_database(client).session_factory() as db:
        future = current_local_date(db) + timedelta(days=1)
    response = client.post(
        f"/habits/{habit_id}/completions/{future.isoformat()}",
        data={"completed": "true", "csrf_token": token},
    )
    assert response.status_code == 400


def test_archive_hides_habit_but_preserves_records(client: TestClient) -> None:
    habit_id = create_habit(client)
    token = csrf_token(client)
    database = client_database(client)
    with database.session_factory() as db:
        today = current_local_date(db)
    client.post(
        f"/habits/{habit_id}/completions/{today.isoformat()}",
        data={"completed": "true", "csrf_token": token},
    )
    response = client.post(
        f"/habits/{habit_id}/archive",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "물 마시기" not in client.get("/today").text
    management_page = client.get("/habits")
    assert "물 마시기" in management_page.text
    assert "보관됨" in management_page.text
    with database.session_factory() as db:
        habit = db.get(Habit, habit_id)
        assert habit is not None
        assert habit.archived_at is not None
        completion = db.scalar(
            select(HabitCompletion).where(HabitCompletion.habit_id == habit_id)
        )
        assert completion is not None
        reminder = db.scalar(select(Reminder).where(Reminder.habit_id == habit_id))
        assert reminder is not None
        assert reminder.is_enabled is False


def test_create_requires_at_least_one_weekday(client: TestClient) -> None:
    login(client)
    token = csrf_token(client)
    response = client.post(
        "/habits",
        data={
            "name": "명상",
            "emoji": "🧘",
            "background_preset": "dawn",
            "csrf_token": token,
        },
    )
    assert response.status_code == 422
    assert "수행 요일을 하나 이상" in response.text


def test_create_allows_empty_emoji_and_shows_default_icon(client: TestClient) -> None:
    login(client)
    token = csrf_token(client)
    database = client_database(client)
    with database.session_factory() as db:
        today = current_local_date(db)

    response = client.post(
        "/habits",
        data={
            "name": "스트레칭",
            "emoji": "",
            "background_preset": "dawn",
            "weekdays": [str(today.weekday())],
            "csrf_token": token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    today_page = client.get("/today")
    assert "스트레칭" in today_page.text
    assert "default-habit-icon" in today_page.text


def test_primary_pages_show_bottom_navigation_and_settings(client: TestClient) -> None:
    login(client)

    for path, current_label in (
        ("/today", "오늘"),
        ("/habits", "습관"),
        ("/calendar", "달력"),
        ("/settings", "설정"),
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert 'aria-label="주 메뉴"' in response.text
        assert 'aria-current="page"' in response.text
        assert current_label in response.text

    assert "Asia/Seoul" in client.get("/settings").text


def test_settings_requires_authentication(client: TestClient) -> None:
    assert client.get("/settings").status_code == 401


def test_habit_pages_require_authentication(client: TestClient) -> None:
    assert client.get("/habits").status_code == 401
    assert client.get("/habits/new").status_code == 401
