import base64
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pywebpush import webpush  # type: ignore[import-untyped]
from sqlalchemy import func, select

from app.config import Settings
from app.db import AppSettings, Base
from app.db.models import PushSubscription
from app.main import create_app
from app.push.generate_vapid_keys import main as generate_vapid_keys
from tests.conftest import csrf_token, login, make_settings


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def vapid_key_pair() -> tuple[str, str]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_value = private_key.private_numbers().private_value.to_bytes(32, "big")
    public_numbers = private_key.public_key().public_numbers()
    public_value = (
        b"\x04"
        + public_numbers.x.to_bytes(32, "big")
        + public_numbers.y.to_bytes(32, "big")
    )
    return encode(public_value), encode(private_value)


@pytest.fixture
def push_client(tmp_path: Path, password_hash: str) -> Iterator[TestClient]:
    public_key, private_key = vapid_key_pair()
    settings = make_settings(
        tmp_path,
        password_hash,
        vapid_public_key=public_key,
        vapid_private_key=private_key,
        vapid_subject="mailto:owner@example.com",
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        Base.metadata.create_all(app.state.database.engine)
        with app.state.database.session_factory() as db:
            db.add(AppSettings(id=1, timezone="Asia/Seoul"))
            db.commit()
        yield test_client


def subscription_payload() -> dict[str, object]:
    return {
        "endpoint": "https://push.example.test/subscription/one",
        "keys": {
            "p256dh": encode(b"\x04" + b"p" * 64),
            "auth": encode(b"a" * 16),
        },
    }


def test_push_config_requires_authentication_and_returns_public_key(
    push_client: TestClient,
) -> None:
    assert push_client.get("/api/push/config").status_code == 401
    login(push_client)

    response = push_client.get("/api/push/config")

    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert response.json()["publicKey"]


def test_subscription_is_csrf_protected_and_idempotently_saved(
    push_client: TestClient,
) -> None:
    login(push_client)
    payload = subscription_payload()
    assert push_client.post("/api/push/subscriptions", json=payload).status_code == 403
    token = csrf_token(push_client)

    for _ in range(2):
        response = push_client.post(
            "/api/push/subscriptions",
            json=payload,
            headers={"X-CSRF-Token": token, "User-Agent": "Test Device"},
        )
        assert response.status_code == 201

    app = cast(FastAPI, push_client.app)
    with app.state.database.session_factory() as db:
        count = db.scalar(select(func.count()).select_from(PushSubscription))
        subscription = db.scalar(select(PushSubscription))
        assert count == 1
        assert subscription is not None
        assert subscription.is_active is True
        assert subscription.user_agent == "Test Device"


def test_subscription_payload_rejects_insecure_endpoint(push_client: TestClient) -> None:
    login(push_client)
    token = csrf_token(push_client)
    payload = subscription_payload()
    payload["endpoint"] = "http://push.example.test/subscription/one"

    response = push_client.post(
        "/api/push/subscriptions",
        json=payload,
        headers={"X-CSRF-Token": token},
    )

    assert response.status_code == 422


def test_partial_vapid_configuration_is_rejected(password_hash: str) -> None:
    settings = Settings(
        _env_file=None,
        habit_tracker_username="owner",
        habit_tracker_password_hash=password_hash,
        session_secret="test-secret-that-is-at-least-thirty-two-characters",
        vapid_public_key="only-one-value",
    )

    with pytest.raises(RuntimeError, match="configured together"):
        settings.validate_push_configuration()


def test_vapid_key_command_generates_matching_environment_values(
    capsys: pytest.CaptureFixture[str],
) -> None:
    generate_vapid_keys()
    generated = dict(
        line.split("=", 1) for line in capsys.readouterr().out.strip().splitlines()
    )
    settings = Settings(
        _env_file=None,
        vapid_public_key=generated["VAPID_PUBLIC_KEY"],
        vapid_private_key=generated["VAPID_PRIVATE_KEY"],
        vapid_subject="mailto:owner@localhost",
    )

    settings.validate_push_configuration()
    assert settings.push_is_configured is True

    receiver_private_key = ec.generate_private_key(ec.SECP256R1())
    receiver_numbers = receiver_private_key.public_key().public_numbers()
    receiver_public_key = encode(
        b"\x04"
        + receiver_numbers.x.to_bytes(32, "big")
        + receiver_numbers.y.to_bytes(32, "big")
    )
    request = webpush(
        subscription_info={
            "endpoint": "https://push.example.test/subscription/one",
            "keys": {"p256dh": receiver_public_key, "auth": encode(b"a" * 16)},
        },
        data='{"title":"습관 알림"}',
        vapid_private_key=generated["VAPID_PRIVATE_KEY"],
        vapid_claims={"sub": "mailto:owner@localhost"},
        curl=True,
    )
    assert isinstance(request, str)
    assert request.startswith("curl")
