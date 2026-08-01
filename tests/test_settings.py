from datetime import time

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import AppSettings, Reminder
from tests.conftest import client_database, csrf_token, login
from tests.test_habits import create_habit


def test_settings_uses_device_iana_timezone(client: TestClient) -> None:
    login(client)

    response = client.get("/settings")

    assert response.status_code == 200
    assert 'action="/settings/timezone"' in response.text
    assert 'name="timezone" value="Asia/Seoul" data-device-timezone-input' in response.text
    assert 'data-saved-timezone="Asia/Seoul"' in response.text
    assert '<span>시간대</span>' in response.text
    assert '<span class="settings-value">Asia/Seoul</span>' in response.text
    assert "기기 시간대" not in response.text
    assert "기기 시간대로 자동 설정됨" not in response.text
    assert "기존 알림은 같은 현지 시각을 유지" not in response.text
    assert "날짜와 알림에 사용할" not in response.text
    assert "common-timezones" not in response.text
    assert response.text.count('class="settings-surface"') == 2
    assert 'data-theme-options' in response.text
    assert 'value="system"' in response.text
    assert 'value="light"' in response.text
    assert 'value="dark"' in response.text
    assert "시스템 설정" in response.text
    assert "Light" in response.text
    assert "Dark" in response.text
    assert response.text.index("알림 권한") < response.text.index("화면 모드")
    assert 'aria-label="시스템 설정"' in response.text
    assert 'aria-label="Light"' in response.text
    assert 'aria-label="Dark"' in response.text

    script = client.get("/static/js/app.js")
    assert "Intl.DateTimeFormat().resolvedOptions().timeZone" in script.text
    assert "deviceTimezoneForm.requestSubmit()" in script.text

    theme_script = client.get("/static/js/theme.js")
    assert "window.localStorage" in theme_script.text
    assert "document.documentElement.dataset.theme" in theme_script.text
    assert "const initialTheme = savedTheme()" in theme_script.text


def test_timezone_change_updates_existing_reminders_without_changing_local_time(
    client: TestClient,
) -> None:
    create_habit(client)
    token = csrf_token(client)

    response = client.post(
        "/settings/timezone",
        data={"timezone": "America/New_York", "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/settings?saved=timezone"
    with client_database(client).session_factory() as db:
        settings = db.get(AppSettings, 1)
        reminder = db.scalar(select(Reminder))
        assert settings is not None
        assert settings.timezone == "America/New_York"
        assert reminder is not None
        assert reminder.timezone == "America/New_York"
        assert reminder.local_time == time(9, 0)

    saved_page = client.get(response.headers["location"])
    assert '<span class="settings-value">America/New_York</span>' in saved_page.text


def test_timezone_change_validates_csrf_and_iana_name(client: TestClient) -> None:
    login(client)

    invalid_csrf = client.post(
        "/settings/timezone",
        data={"timezone": "UTC", "csrf_token": "invalid"},
    )
    assert invalid_csrf.status_code == 403
    assert "요청이 만료되었습니다." in invalid_csrf.text

    invalid_timezone = client.post(
        "/settings/timezone",
        data={"timezone": "Not/A_Timezone", "csrf_token": csrf_token(client)},
    )
    assert invalid_timezone.status_code == 422
    assert "올바른 IANA 시간대" in invalid_timezone.text

    with client_database(client).session_factory() as db:
        settings = db.get(AppSettings, 1)
        assert settings is not None
        assert settings.timezone == "Asia/Seoul"


def test_timezone_change_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/settings/timezone",
        data={"timezone": "UTC", "csrf_token": "invalid"},
    )

    assert response.status_code == 401
