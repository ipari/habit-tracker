from datetime import UTC, datetime, timedelta
from pathlib import Path

from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.auth.security import create_session_token, read_session_token
from app.config import Settings
from app.main import create_app
from tests.conftest import TEST_PASSWORD, csrf_token, login, make_settings


def test_login_and_logout(client: TestClient) -> None:
    token = csrf_token(client)
    response = client.post(
        "/login",
        data={"username": "owner", "password": TEST_PASSWORD, "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/today"
    assert "session" in client.cookies
    session_cookie = response.headers["set-cookie"]
    assert "HttpOnly" in session_cookie
    assert "SameSite=lax" in session_cookie

    today = client.get("/today")
    assert today.status_code == 200
    assert "<h1>오늘</h1>" in today.text
    assert "owner님의 하루" not in today.text

    response = client.post("/logout", data={"csrf_token": token}, follow_redirects=False)
    assert response.status_code == 303
    assert client.get("/today").status_code == 401


def test_unauthenticated_browser_and_htmx_requests_redirect_to_login(client: TestClient) -> None:
    browser = client.get("/today", headers={"accept": "text/html"}, follow_redirects=False)
    assert browser.status_code == 303
    assert browser.headers["location"] == "/login"

    htmx = client.get("/today", headers={"HX-Request": "true"}, follow_redirects=False)
    assert htmx.status_code == 401
    assert htmx.headers["HX-Redirect"] == "/login"


def test_invalid_credentials_do_not_reveal_username(client: TestClient) -> None:
    token = csrf_token(client)
    missing = client.post(
        "/login",
        data={"username": "missing", "password": "wrong password", "csrf_token": token},
    )
    wrong = client.post(
        "/login",
        data={"username": "owner", "password": "wrong password", "csrf_token": token},
    )
    message = "아이디 또는 비밀번호를 확인해 주세요."
    assert missing.status_code == wrong.status_code == 401
    assert message in missing.text
    assert message in wrong.text


def test_login_rejects_missing_csrf(client: TestClient) -> None:
    response = client.post(
        "/login",
        data={"username": "owner", "password": TEST_PASSWORD, "csrf_token": "x"},
    )
    assert response.status_code == 403


def test_login_is_rate_limited(client: TestClient) -> None:
    token = csrf_token(client)
    for attempt in range(5):
        response = client.post(
            "/login",
            data={"username": f"wrong-{attempt}", "password": "wrong", "csrf_token": token},
        )
        assert response.status_code == 401
    limited = client.post(
        "/login",
        data={"username": "another-name", "password": "wrong", "csrf_token": token},
    )
    assert limited.status_code == 429


def test_password_hash_change_invalidates_existing_session(
    tmp_path: Path, password_hash: str
) -> None:
    original = make_settings(tmp_path, password_hash)
    with TestClient(create_app(original)) as first_client:
        session = login(first_client)

    changed = make_settings(tmp_path, PasswordHasher().hash("a completely new password"))
    with TestClient(create_app(changed)) as restarted_client:
        restarted_client.cookies.set("session", session)
        assert restarted_client.get("/today").status_code == 401


def test_tampered_and_expired_sessions_are_rejected(settings: Settings) -> None:
    now = datetime.now(UTC)
    token = create_session_token(settings, now)
    assert read_session_token(settings, token, now) is not None
    assert read_session_token(settings, token + "x", now) is None
    assert read_session_token(settings, token, now + timedelta(days=31)) is None


def test_session_secret_change_invalidates_existing_session(
    tmp_path: Path, password_hash: str
) -> None:
    original = make_settings(tmp_path, password_hash)
    token = create_session_token(original)
    changed = make_settings(
        tmp_path,
        password_hash,
        session_secret="another-test-secret-that-is-at-least-thirty-two-characters",
    )
    assert read_session_token(changed, token) is None


def test_health_endpoints(client: TestClient) -> None:
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ok"}
