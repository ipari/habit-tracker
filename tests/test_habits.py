from datetime import time, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import Habit, HabitCompletion, HabitSchedule, Reminder
from app.habits.routes import detail_schedule_label
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
    assert f'href="/habits/{habit_id}?from=today"' in today_page.text
    assert f'href="/habits/{habit_id}/edit"' not in today_page.text
    assert f'href="/habits/{habit_id}/share"' not in today_page.text

    with client_database(client).session_factory() as db:
        schedule = db.scalar(select(HabitSchedule).where(HabitSchedule.habit_id == habit_id))
        assert schedule is not None
        assert schedule.effective_from == current_local_date(db)


def test_today_orders_incomplete_habits_by_time_and_reranks_after_completion(
    client: TestClient,
) -> None:
    login(client)
    token = csrf_token(client)
    database = client_database(client)
    habit_ids: dict[str, int] = {}
    with database.session_factory() as db:
        today = current_local_date(db)
        specs = (
            ("늦은 미완료", time(13, 0), False),
            ("빠른 미완료", time(8, 0), False),
            ("시간 없음", None, False),
            ("완료 습관", time(7, 0), True),
        )
        for name, reminder_time, completed in specs:
            habit = Habit(name=name, emoji="", background_preset="dawn")
            db.add(habit)
            db.flush()
            habit_ids[name] = habit.id
            db.add(
                HabitSchedule(
                    habit=habit,
                    weekdays_mask=127,
                    effective_from=today - timedelta(days=7),
                )
            )
            if reminder_time is not None:
                db.add(
                    Reminder(
                        habit=habit,
                        weekdays_mask=127,
                        local_time=reminder_time,
                        timezone="Asia/Seoul",
                        is_enabled=True,
                    )
                )
            if completed:
                db.add(HabitCompletion(habit=habit, local_date=today))
        db.commit()

    page = client.get("/today")
    assert page.text.index("빠른 미완료") < page.text.index("늦은 미완료")
    assert page.text.index("늦은 미완료") < page.text.index("시간 없음")
    assert page.text.index("시간 없음") < page.text.index("완료 습관")
    assert "매일" in page.text
    assert "8:00 AM" in page.text

    response = client.post(
        f"/habits/{habit_ids['빠른 미완료']}/completions/{today.isoformat()}",
        data={"completed": "true", "csrf_token": token},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert 'id="today-habits"' in response.text
    assert response.text.index("늦은 미완료") < response.text.index("시간 없음")
    assert response.text.index("시간 없음") < response.text.index("완료 습관")
    assert response.text.index("완료 습관") < response.text.index("빠른 미완료")


def test_habit_detail_collects_management_actions(client: TestClient) -> None:
    habit_id = create_habit(client)
    with client_database(client).session_factory() as db:
        today = current_local_date(db)

    detail = client.get(f"/habits/{habit_id}")

    assert detail.status_code == 200
    assert "물 마시기" in detail.text
    assert "<strong>0</strong>" in detail.text
    assert "회 연속 달성" in detail.text
    assert f"{today.year}년 {today.month}월 {today.day}일 처음 시작" in detail.text
    assert f'href="/habits/{habit_id}/share?from=habits"' in detail.text
    assert "<span>공유</span>" in detail.text
    assert "습관 공유" not in detail.text
    assert "성과 공유" not in detail.text
    assert "primary-action" not in detail.text
    assert f'href="/habits/{habit_id}/edit?from=habits"' in detail.text
    assert f'action="/habits/{habit_id}/archive"' in detail.text
    archive_confirmation = (
        'data-confirm="과거 달성 기록과 일정은 삭제되지 않습니다. 습관을 삭제할까요?"'
    )
    assert archive_confirmation in detail.text
    assert "<span>요일</span>" in detail.text
    assert "<span>시간</span>" in detail.text
    assert "9:00 AM" in detail.text
    assert "<span>알림</span>" in detail.text
    assert "<strong>꺼짐</strong>" in detail.text
    assert "공유 배경" not in detail.text

    management = client.get("/habits")
    assert f'href="/habits/{habit_id}?from=habits"' in management.text
    assert f'href="/habits/{habit_id}/share"' not in management.text
    assert f'href="/habits/{habit_id}/edit"' not in management.text


def test_habit_detail_uses_compact_schedule_labels() -> None:
    assert detail_schedule_label((0, 2, 4)) == "월 · 수 · 금"
    assert detail_schedule_label(tuple(range(5))) == "주중"
    assert detail_schedule_label((4, 5)) == "주말"
    assert detail_schedule_label((5, 6)) == "주말"
    assert detail_schedule_label(tuple(range(7))) == "매일"


def test_habit_list_summarizes_schedule_streak_and_reminder(client: TestClient) -> None:
    habit_id = create_habit(client, weekdays=list(range(5)))
    token = csrf_token(client)
    response = client.post(
        f"/habits/{habit_id}",
        data={
            "name": "물 마시기",
            "emoji": "💧",
            "background_preset": "ocean",
            "weekdays": [str(day) for day in range(5)],
            "reminder_enabled": "true",
            "reminder_time": "13:00",
            "return_to": "habits",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    response = client.post(
        "/habits",
        data={
            "name": "주말 산책",
            "emoji": "🚶",
            "background_preset": "forest",
            "weekdays": ["5", "6"],
            "reminder_time": "09:00",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    with client_database(client).session_factory() as db:
        today = current_local_date(db)
        habit_without_time = Habit(
            name="명상",
            emoji="🧘",
            background_preset="dawn",
        )
        db.add(habit_without_time)
        db.flush()
        db.add(
            HabitSchedule(
                habit=habit_without_time,
                weekdays_mask=127,
                effective_from=today,
            )
        )
        db.commit()

    page = client.get("/habits")
    assert "<h1>습관들</h1>" in page.text
    assert "연속 0회" in page.text
    assert "주중" in page.text
    assert "1:00 PM" in page.text
    assert "9:00 AM" in page.text
    assert "주말" in page.text
    assert "알림 없음" not in page.text
    assert page.text.count('class="reminder-clock"') == 1
    assert "알림 켜짐" in page.text
    habit_without_time_row = page.text.split("명상 상세 보기", 1)[1].split("</a>", 1)[0]
    assert " AM" not in habit_without_time_row
    assert " PM" not in habit_without_time_row
    assert "reminder-clock" not in habit_without_time_row
    assert ">활성<" not in page.text
    assert "Asia/Seoul" not in page.text


def test_edit_returns_to_the_page_it_was_opened_from(client: TestClient) -> None:
    habit_id = create_habit(client)
    token = csrf_token(client)
    database = client_database(client)
    with database.session_factory() as db:
        today = current_local_date(db)

    today_detail = client.get(f"/habits/{habit_id}?from=today")
    assert 'class="back-link" href="/today"' in today_detail.text
    assert f'href="/habits/{habit_id}/edit?from=today"' in today_detail.text

    from_today = client.get(f"/habits/{habit_id}/edit?from=today")
    assert 'class="back-link" href="/today"' in from_today.text
    assert 'name="return_to" value="today"' in from_today.text

    habits_detail = client.get(f"/habits/{habit_id}?from=habits")
    assert 'class="back-link" href="/habits"' in habits_detail.text
    assert f'href="/habits/{habit_id}/edit?from=habits"' in habits_detail.text

    from_habits = client.get(f"/habits/{habit_id}/edit?from=habits")
    assert 'class="back-link" href="/habits"' in from_habits.text
    assert 'name="return_to" value="habits"' in from_habits.text

    response = client.post(
        f"/habits/{habit_id}",
        data={
            "name": "물 마시기",
            "emoji": "💧",
            "background_preset": "ocean",
            "weekdays": [str(today.weekday())],
            "reminder_time": "09:00",
            "return_to": "today",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/today"


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
        assert 'class="habit-toggle"' in response.text
        assert 'aria-pressed="true"' in response.text
        assert "✓" in response.text
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
    assert '<details class="past-habits">' in management_page.text
    assert "지난 습관들" in management_page.text
    assert "보관됨" not in management_page.text
    assert management_page.text.index("past-habits") < management_page.text.index("물 마시기")
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
    assert client.get("/habits/1").status_code == 401
