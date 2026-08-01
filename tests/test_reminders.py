from datetime import time
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Habit, Reminder
from app.domain.schedules import weekdays_to_mask
from tests.conftest import client_database, csrf_token, login
from tests.test_habits import create_habit


def test_new_habit_gets_disabled_reminder_using_habit_weekdays(
    client: TestClient,
) -> None:
    habit_id = create_habit(client, weekdays=[0, 2, 4])

    with client_database(client).session_factory() as db:
        reminder = db.scalar(select(Reminder).where(Reminder.habit_id == habit_id))
        assert reminder is not None
        assert reminder.is_enabled is False
        assert reminder.weekdays_mask == weekdays_to_mask([0, 2, 4])
        assert reminder.local_time == time(9, 0)
        assert reminder.timezone == "Asia/Seoul"


def test_enabled_reminder_ignores_client_supplied_separate_weekdays(
    client: TestClient,
) -> None:
    login(client)
    token = csrf_token(client)
    form_data: dict[str, Any] = {
        "name": "저녁 산책",
        "emoji": "🚶",
        "background_preset": "forest",
        "weekdays": [0, 2, 4],
        "reminder_enabled": "true",
        "reminder_time": "19:30",
        "reminder_weekdays": [1, 3],
        "csrf_token": token,
    }

    response = client.post("/habits", data=form_data, follow_redirects=False)

    assert response.status_code == 303
    with client_database(client).session_factory() as db:
        reminder = db.scalar(select(Reminder).join(Habit).where(Habit.name == "저녁 산책"))
        assert reminder is not None
        assert reminder.is_enabled is True
        assert reminder.weekdays_mask == weekdays_to_mask([0, 2, 4])
        assert reminder.local_time == time(19, 30)


def test_edit_updates_following_reminder_with_new_habit_weekdays(
    client: TestClient,
) -> None:
    habit_id = create_habit(client, weekdays=[0])
    token = csrf_token(client)

    response = client.post(
        f"/habits/{habit_id}",
        data={
            "name": "물 마시기",
            "emoji": "💧",
            "background_preset": "ocean",
            "weekdays": ["1", "3"],
            "reminder_enabled": "true",
            "reminder_time": "08:15",
            "csrf_token": token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    with client_database(client).session_factory() as db:
        reminders = db.scalars(select(Reminder).where(Reminder.habit_id == habit_id)).all()
        assert len(reminders) == 1
        reminder = reminders[0]
        assert reminder.is_enabled is True
        assert reminder.weekdays_mask == weekdays_to_mask([1, 3])
        assert reminder.local_time == time(8, 15)


def test_reminder_rejects_invalid_local_time(client: TestClient) -> None:
    login(client)
    token = csrf_token(client)

    response = client.post(
        "/habits",
        data={
            "name": "아침 운동",
            "emoji": "",
            "background_preset": "dawn",
            "weekdays": ["0"],
            "reminder_time": "25:00",
            "csrf_token": token,
        },
    )

    assert response.status_code == 422
    assert "알림 시간을 올바르게" in response.text


def test_reminder_form_shows_saved_values_and_timezone(client: TestClient) -> None:
    habit_id = create_habit(client, weekdays=[0, 2])

    response = client.get(f"/habits/{habit_id}/edit")

    assert response.status_code == 200
    assert 'name="reminder_time" type="time" required value="09:00"' in response.text
    assert "기준 시간대:" in response.text
    assert "Asia/Seoul" in response.text
    assert "현재는 알림 설정만 저장됩니다." in response.text
    assert "알림은 항상 위에서 선택한 수행 요일" in response.text
    assert "수행 요일과 동일" not in response.text
    assert 'name="reminder_weekdays"' not in response.text
