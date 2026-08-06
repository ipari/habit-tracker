from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.accounts.routes import signup_rate_limiter
from app.auth.routes import rate_limiter
from app.config import Settings
from app.db import AppSettings, Base, Habit, PushSubscription, User
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
        "habit_tracker_username": "admin",
        "habit_tracker_password_hash": password_hash,
        "session_secret": "test-secret-that-is-at-least-thirty-two-characters",
        "session_cookie_secure": False,
    }
    values.update(overrides)
    return Settings.model_validate(values)


@pytest.fixture(autouse=True)
def reset_rate_limiter() -> None:
    rate_limiter._failures.clear()
    signup_rate_limiter._failures.clear()


@pytest.fixture
def settings(tmp_path: Path, password_hash: str) -> Settings:
    return make_settings(tmp_path, password_hash)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as test_client:
        Base.metadata.create_all(app.state.database.engine)
        with app.state.database.session_factory() as db:
            user = User(
                email="owner",
                normalized_email="owner",
                password_hash=settings.habit_tracker_password_hash.get_secret_value(),
            )
            db.add(user)
            db.flush()
            db.add(AppSettings(id=1, user_id=user.id, timezone="Asia/Seoul"))
            db.commit()

        def assign_test_owner(session: Session, *_args: object) -> None:
            for item in session.new:
                if isinstance(item, (Habit, PushSubscription)) and item.user_id is None:
                    item.user_id = 1

        event.listen(app.state.database.session_factory, "before_flush", assign_test_owner)
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
    assert response.headers["location"] == "/today"
    database = client_database(client)
    with database.session_factory() as db:
        user = db.scalar(select(User).where(User.normalized_email == "owner"))
        assert user is not None
        for habit in db.scalars(select(Habit).where(Habit.user_id.is_(None))).all():
            habit.user_id = user.id
        for subscription in db.scalars(
            select(PushSubscription).where(PushSubscription.user_id.is_(None))
        ).all():
            subscription.user_id = user.id
        db.commit()
    session = client.cookies.get("session")
    assert session is not None
    return cast(str, session)


def client_database(client: TestClient) -> Database:
    app = cast(FastAPI, client.app)
    return cast(Database, app.state.database)
