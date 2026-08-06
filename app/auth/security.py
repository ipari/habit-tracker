import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import User, UserSession

password_hasher = PasswordHasher()


@dataclass(frozen=True)
class AuthenticatedIdentity:
    username: str
    role: str
    user_id: int | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def _secret(settings: Settings) -> str:
    return settings.session_secret.get_secret_value()


def credential_fingerprint(settings: Settings) -> str:
    credentials = (
        f"{settings.habit_tracker_username}\0"
        f"{settings.habit_tracker_password_hash.get_secret_value()}"
    )
    return hmac.new(_secret(settings).encode(), credentials.encode(), hashlib.sha256).hexdigest()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def ensure_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def create_session_token(
    settings: Settings,
    db: Session,
    *,
    user: User | None = None,
    role: str = "member",
    now: datetime | None = None,
) -> str:
    if role not in {"admin", "member"}:
        raise ValueError("Invalid session role")
    if (role == "member") != (user is not None):
        raise ValueError("Member sessions require a user")
    issued_at = now or datetime.now(UTC)
    token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            user=user,
            role=role,
            token_hash=token_hash(token),
            credential_fingerprint=(
                credential_fingerprint(settings) if role == "admin" else ""
            ),
            expires_at=issued_at + timedelta(hours=settings.session_ttl_hours),
            last_used_at=issued_at,
        )
    )
    db.flush()
    return token


def read_session_token(
    settings: Settings,
    db: Session,
    token: str | None,
    now: datetime | None = None,
) -> AuthenticatedIdentity | None:
    if not token:
        return None
    session = db.scalar(
        select(UserSession).where(UserSession.token_hash == token_hash(token))
    )
    if session is None or session.revoked_at is not None:
        return None
    current_time = now or datetime.now(UTC)
    if ensure_utc(session.expires_at) <= current_time:
        return None
    if session.role == "admin":
        if not hmac.compare_digest(
            session.credential_fingerprint, credential_fingerprint(settings)
        ):
            return None
        return AuthenticatedIdentity(
            username=settings.habit_tracker_username, role="admin"
        )
    user = session.user
    if user is None or not user.is_active:
        return None
    return AuthenticatedIdentity(username=user.email, role="member", user_id=user.id)


def revoke_session(db: Session, token: str | None) -> None:
    if not token:
        return
    session = db.scalar(
        select(UserSession).where(UserSession.token_hash == token_hash(token))
    )
    if session is not None and session.revoked_at is None:
        session.revoked_at = datetime.now(UTC)


def revoke_user_sessions(db: Session, user_id: int) -> None:
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


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
