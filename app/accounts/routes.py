from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.accounts.service import normalize_email, validate_new_password
from app.auth.dependencies import DbSession
from app.auth.rate_limit import LoginRateLimiter
from app.auth.routes import client_key
from app.auth.security import (
    create_session_token,
    ensure_utc,
    revoke_user_sessions,
    token_hash,
)
from app.db.models import AppSettings, Invitation, PasswordResetToken, User
from app.web import render_template, request_has_valid_csrf

router = APIRouter()
signup_rate_limiter = LoginRateLimiter()


def invitation_for_code(db: DbSession, code: str) -> Invitation | None:
    if len(code) != 12:
        return None
    return db.scalar(select(Invitation).where(Invitation.code == code))


def signup_context(
    invitation: Invitation | None,
    *,
    email: str = "",
    error: str | None = None,
) -> dict[str, object]:
    return {
        "invitation": invitation,
        "email": email,
        "error": error,
        "available": invitation is not None and invitation.is_active,
    }


@router.get("/invite/{code}", response_class=HTMLResponse, name="signup_page")
def signup_page(code: str, request: Request, db: DbSession) -> HTMLResponse:
    invitation = invitation_for_code(db, code)
    available = invitation is not None and invitation.is_active
    return render_template(
        request,
        "auth/signup.html",
        signup_context(invitation),
        200 if available else 410,
    )


@router.post("/invite/{code}", response_class=HTMLResponse)
def signup(
    code: str,
    request: Request,
    db: DbSession,
    email: Annotated[str, Form(max_length=254)],
    password: Annotated[str, Form(max_length=1024)],
    password_confirmation: Annotated[str, Form(max_length=1024)],
    csrf_token: Annotated[str, Form()],
) -> Response:
    invitation = invitation_for_code(db, code)
    if invitation is None or not invitation.is_active:
        return render_template(
            request, "auth/signup.html", signup_context(invitation), 410
        )
    if not request_has_valid_csrf(request, csrf_token):
        return render_template(
            request,
            "auth/signup.html",
            signup_context(invitation, email=email, error="요청이 만료되었습니다."),
            403,
        )
    key = f"signup:{client_key(request)}"
    if signup_rate_limiter.is_limited(key):
        return render_template(
            request,
            "auth/signup.html",
            signup_context(invitation, email=email, error="잠시 후 다시 시도해 주세요."),
            429,
        )
    try:
        display_email, normalized_email = normalize_email(email)
        password_hash = validate_new_password(password, password_confirmation)
        if db.scalar(select(User.id).where(User.normalized_email == normalized_email)):
            raise ValueError("이미 가입된 이메일입니다.")
        now = datetime.now(UTC)
        user = User(
            email=display_email,
            normalized_email=normalized_email,
            password_hash=password_hash,
            invitation=invitation,
            last_login_at=now,
        )
        db.add(user)
        db.flush()
        db.add(AppSettings(user_id=user.id, timezone="UTC"))
        invitation.last_joined_at = now
        session_token = create_session_token(
            request.app.state.settings, db, user=user, role="member"
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        signup_rate_limiter.record_failure(key)
        return render_template(
            request,
            "auth/signup.html",
            signup_context(invitation, email=email, error=str(exc)),
            422,
        )
    except (IntegrityError, SQLAlchemyError):
        db.rollback()
        signup_rate_limiter.record_failure(key)
        return render_template(
            request,
            "auth/signup.html",
            signup_context(invitation, email=email, error="가입하지 못했습니다."),
            503,
        )
    signup_rate_limiter.clear(key)
    response = RedirectResponse("/today", status_code=status.HTTP_303_SEE_OTHER)
    settings = request.app.state.settings
    response.set_cookie(
        "session",
        session_token,
        max_age=settings.session_ttl_hours * 3600,
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response


def reset_for_token(db: DbSession, raw_token: str) -> PasswordResetToken | None:
    reset = db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash(raw_token)
        )
    )
    if (
        reset is None
        or reset.used_at is not None
        or ensure_utc(reset.expires_at) <= datetime.now(UTC)
        or not reset.user.is_active
    ):
        return None
    return reset


@router.get("/reset/{raw_token}", response_class=HTMLResponse)
def reset_page(raw_token: str, request: Request, db: DbSession) -> HTMLResponse:
    reset = reset_for_token(db, raw_token)
    return render_template(
        request,
        "auth/reset.html",
        {"available": reset is not None, "raw_token": raw_token, "error": None},
        200 if reset is not None else 410,
    )


@router.post("/reset/{raw_token}", response_class=HTMLResponse)
def reset_password(
    raw_token: str,
    request: Request,
    db: DbSession,
    password: Annotated[str, Form(max_length=1024)],
    password_confirmation: Annotated[str, Form(max_length=1024)],
    csrf_token: Annotated[str, Form()],
) -> Response:
    reset = reset_for_token(db, raw_token)
    if reset is None:
        return render_template(
            request,
            "auth/reset.html",
            {"available": False, "raw_token": raw_token, "error": None},
            410,
        )
    if not request_has_valid_csrf(request, csrf_token):
        return render_template(
            request,
            "auth/reset.html",
            {"available": True, "raw_token": raw_token, "error": "요청이 만료되었습니다."},
            403,
        )
    try:
        reset.user.password_hash = validate_new_password(password, password_confirmation)
        reset.used_at = datetime.now(UTC)
        revoke_user_sessions(db, reset.user_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        return render_template(
            request,
            "auth/reset.html",
            {"available": True, "raw_token": raw_token, "error": str(exc)},
            422,
        )
    except SQLAlchemyError:
        db.rollback()
        return render_template(
            request,
            "auth/reset.html",
            {"available": True, "raw_token": raw_token, "error": "변경하지 못했습니다."},
            503,
        )
    return RedirectResponse("/login?reset=1", status_code=status.HTTP_303_SEE_OTHER)
