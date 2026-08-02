from datetime import time
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Habit, Reminder
from app.domain.schedules import weekdays_to_mask
from tests.conftest import client_database, csrf_token, login
from tests.test_habits import create_habit


def test_new_habit_gets_enabled_reminder_when_time_is_enabled(
    client: TestClient,
) -> None:
    habit_id = create_habit(client, weekdays=[0, 2, 4])

    with client_database(client).session_factory() as db:
        reminder = db.scalar(select(Reminder).where(Reminder.habit_id == habit_id))
        assert reminder is not None
        assert reminder.is_enabled is True
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
        "time_enabled": "true",
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
            "time_enabled": "true",
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
            "time_enabled": "true",
            "reminder_time": "25:00",
            "csrf_token": token,
        },
    )

    assert response.status_code == 422
    assert "시간을 올바르게" in response.text


def test_reminder_form_shows_saved_values_and_timezone(client: TestClient) -> None:
    habit_id = create_habit(client, weekdays=[0, 2])

    response = client.get(f"/habits/{habit_id}/edit")

    assert response.status_code == 200
    time_toggle = response.text.split('id="time-enabled"', 1)[1].split(">", 1)[0]
    assert "checked" in time_toggle
    assert 'id="time-settings"' in response.text
    assert 'aria-disabled="false"' in response.text
    assert 'name="reminder_time" type="time" required value="09:00"' in response.text
    assert '<label for="reminder-time">시간</label>' in response.text
    assert "알림 시간" not in response.text
    assert "기준 시간대:" not in response.text
    assert "이 기기의 알림 연결도 완료" not in response.text
    assert "알림은 항상 위에서 선택한 수행 요일" not in response.text
    assert "선택한 요일과 현지 시간에 알려드려요" not in response.text
    assert "<legend>수행 요일" not in response.text
    assert "<legend>요일" in response.text
    assert "수행 요일과 동일" not in response.text
    assert 'name="reminder_weekdays"' not in response.text
    assert 'id="reminder-enabled"' in response.text
    assert "checked" in response.text
    assert "시간을 지정하거나 변경하면 알림 받기가 자동으로 켜집니다." in response.text


def test_changing_reminder_time_enables_notification_toggle(client: TestClient) -> None:
    login(client)
    script = client.get("/static/js/app.js")

    assert 'document.querySelector("#time-enabled")' in script.text
    assert 'document.querySelector("[data-time-settings]")' in script.text
    assert 'document.querySelector("#reminder-time")' in script.text
    assert 'document.querySelector("#reminder-enabled")' in script.text
    assert "timeSettings.disabled = !isEnabled" in script.text
    assert "reminderEnabledInput.checked = true" in script.text


def test_new_habit_can_be_created_without_time(client: TestClient) -> None:
    login(client)
    token = csrf_token(client)

    form = client.get("/habits/new")
    time_toggle = form.text.split('id="time-enabled"', 1)[1].split(">", 1)[0]
    assert "checked" not in time_toggle
    assert 'id="time-settings"' in form.text
    assert 'aria-disabled="true"' in form.text

    response = client.post(
        "/habits",
        data={
            "name": "시간 없는 습관",
            "emoji": "",
            "background_preset": "dawn",
            "weekdays": ["0", "2", "4"],
            "csrf_token": token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    with client_database(client).session_factory() as db:
        habit = db.scalar(select(Habit).where(Habit.name == "시간 없는 습관"))
        assert habit is not None
        assert habit.reminder is None

    habits_page = client.get("/habits")
    habit_row = habits_page.text.split("시간 없는 습관 상세 보기", 1)[1].split("</a>", 1)[0]
    assert "AM" not in habit_row
    assert "PM" not in habit_row

    detail = client.get(f"/habits/{habit.id}")
    assert "<span>시간</span>" not in detail.text
    assert "<span>알림</span>" not in detail.text


def test_disabling_time_removes_saved_reminder(client: TestClient) -> None:
    habit_id = create_habit(client, weekdays=[0, 2, 4])

    response = client.post(
        f"/habits/{habit_id}",
        data={
            "name": "물 마시기",
            "emoji": "💧",
            "background_preset": "ocean",
            "weekdays": ["0", "2", "4"],
            "reminder_time": "09:00",
            "csrf_token": csrf_token(client),
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    with client_database(client).session_factory() as db:
        assert db.scalar(select(Reminder).where(Reminder.habit_id == habit_id)) is None

    edit_form = client.get(f"/habits/{habit_id}/edit")
    time_toggle = edit_form.text.split('id="time-enabled"', 1)[1].split(">", 1)[0]
    assert "checked" not in time_toggle
    assert 'aria-disabled="true"' in edit_form.text
