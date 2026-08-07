import re
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth.security import password_hasher, token_hash
from app.db.models import Invitation, PasswordResetToken

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalize_email(value: str) -> tuple[str, str]:
    email = value.strip()
    normalized = email.casefold()
    if len(email) > 254 or not EMAIL_PATTERN.fullmatch(email):
        raise ValueError("올바른 이메일 주소를 입력해 주세요.")
    return email, normalized


def validate_new_password(password: str, confirmation: str) -> str:
    if len(password) < 8 or len(password) > 1024:
        raise ValueError("비밀번호는 8자 이상으로 입력해 주세요.")
    if password != confirmation:
        raise ValueError("비밀번호 확인이 일치하지 않습니다.")
    return password_hasher.hash(password)


def create_invitation(
    db: Session, *, creator_user_id: int | None = None, created_by_admin: bool = False
) -> Invitation:
    if (creator_user_id is None) == (not created_by_admin):
        raise ValueError("Invitation creator is required")
    creator_filter = (
        Invitation.created_by_admin.is_(True)
        if created_by_admin
        else Invitation.created_by_user_id == creator_user_id
    )
    existing = db.scalar(
        select(Invitation)
        .where(creator_filter, Invitation.is_active.is_(True))
        .order_by(Invitation.created_at.desc(), Invitation.id.desc())
        .limit(1)
    )
    if existing is not None:
        return existing
    for _attempt in range(5):
        code = secrets.token_urlsafe(9)
        if len(code) == 12 and db.scalar(
            select(Invitation.id).where(Invitation.code == code)
        ) is None:
            invitation = Invitation(
                code=code,
                created_by_user_id=creator_user_id,
                created_by_admin=created_by_admin,
            )
            db.add(invitation)
            db.flush()
            return invitation
    raise RuntimeError("Could not generate a unique invitation")


def cancel_invitation(invitation: Invitation) -> None:
    if invitation.is_active:
        invitation.is_active = False
        invitation.canceled_at = datetime.now(UTC)


def create_password_reset(db: Session, user_id: int) -> tuple[PasswordResetToken, str]:
    now = datetime.now(UTC)
    db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    raw_token = secrets.token_urlsafe(32)
    reset = PasswordResetToken(
        user_id=user_id,
        token_hash=token_hash(raw_token),
        expires_at=now + timedelta(hours=1),
    )
    db.add(reset)
    db.flush()
    return reset, raw_token
