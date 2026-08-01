import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config import Settings

SESSION_VERSION = 1
password_hasher = PasswordHasher()


@dataclass(frozen=True)
class AuthenticatedIdentity:
    username: str


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def _secret(settings: Settings) -> str:
    return settings.session_secret.get_secret_value()


def _credential_fingerprint(settings: Settings) -> str:
    credentials = (
        f"{settings.habit_tracker_username}\0"
        f"{settings.habit_tracker_password_hash.get_secret_value()}"
    )
    return hmac.new(_secret(settings).encode(), credentials.encode(), hashlib.sha256).hexdigest()


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_session_token(settings: Settings, now: datetime | None = None) -> str:
    issued_at = now or datetime.now(UTC)
    payload = {
        "v": SESSION_VERSION,
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + timedelta(hours=settings.session_ttl_hours)).timestamp()),
        "fp": _credential_fingerprint(settings),
    }
    encoded = _encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = hmac.new(_secret(settings).encode(), encoded.encode(), hashlib.sha256).digest()
    return f"{encoded}.{_encode(signature)}"


def read_session_token(
    settings: Settings, token: str | None, now: datetime | None = None
) -> AuthenticatedIdentity | None:
    if not token:
        return None
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected_signature = hmac.new(
            _secret(settings).encode(), encoded.encode(), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_decode(supplied_signature), expected_signature):
            return None
        payload: Any = json.loads(_decode(encoded))
        if not isinstance(payload, dict):
            return None
        if payload.get("v") != SESSION_VERSION:
            return None
        expires_at = payload.get("exp")
        fingerprint = payload.get("fp")
        if not isinstance(expires_at, int) or not isinstance(fingerprint, str):
            return None
        current_time = now or datetime.now(UTC)
        if expires_at <= int(current_time.timestamp()):
            return None
        if not hmac.compare_digest(fingerprint, _credential_fingerprint(settings)):
            return None
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    return AuthenticatedIdentity(username=settings.habit_tracker_username)


def create_csrf_token(secret: str) -> str:
    token = secrets.token_urlsafe(32)
    signature = hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()
    return f"{token}.{signature}"


def verify_csrf_token(cookie_token: str | None, form_token: str | None, secret: str) -> bool:
    if not cookie_token or not form_token or not hmac.compare_digest(cookie_token, form_token):
        return False
    try:
        token, signature = cookie_token.rsplit(".", 1)
    except ValueError:
        return False
    expected = hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)
