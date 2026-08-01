from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.routes import rate_limiter
from app.config import Settings
from app.db import AppSettings, Base
from app.db.session import Database
from app.main import create_app

TEST_PASSWORD = "correct horse battery staple"


@pytest.fixture(scope="session")
def password_hash() -> str:
    return PasswordHasher().hash(TEST_PASSWORD)


def make_settings(tmp_path: Path, password_hash: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": "test",
        "database_url": f"sqlite:///{tmp_path / 'test.db'}",
        "habit_tracker_username": "owner",
        "habit_tracker_password_hash": password_hash,
        "session_secret": "test-secret-that-is-at-least-thirty-two-characters",
        "session_cookie_secure": False,
    }
    values.update(overrides)
    return Settings.model_validate(values)


@pytest.fixture(autouse=True)
def reset_rate_limiter() -> None:
    rate_limiter._failures.clear()


@pytest.fixture
def settings(tmp_path: Path, password_hash: str) -> Settings:
    return make_settings(tmp_path, password_hash)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as test_client:
        Base.metadata.create_all(app.state.database.engine)
        with app.state.database.session_factory() as db:
            db.add(AppSettings(id=1, timezone="Asia/Seoul"))
            db.commit()
        yield test_client


def csrf_token(client: TestClient) -> str:
    response = client.get("/login")
    assert response.status_code == 200
    token = client.cookies.get("csrf")
    assert token is not None
    return cast(str, token)


def login(client: TestClient) -> str:
    token = csrf_token(client)
    response = client.post(
        "/login",
        data={"username": "owner", "password": TEST_PASSWORD, "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    session = client.cookies.get("session")
    assert session is not None
    return cast(str, session)


def client_database(client: TestClient) -> Database:
    app = cast(FastAPI, client.app)
    return cast(Database, app.state.database)
