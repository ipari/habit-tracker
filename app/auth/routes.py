import hmac
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.auth.dependencies import DbSession, optional_identity
from app.auth.rate_limit import LoginRateLimiter
from app.auth.security import (
    create_csrf_token,
    create_session_token,
    revoke_session,
    verify_csrf_token,
    verify_password,
)
from app.db.models import User

router = APIRouter()
rate_limiter = LoginRateLimiter()


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def login_response(
    request: Request,
    error: str | None = None,
    status_code: int = 200,
    *,
    rotate_csrf: bool = False,
) -> HTMLResponse:
    settings = request.app.state.settings
    secret = settings.session_secret.get_secret_value()
    existing_token = None if rotate_csrf else request.cookies.get("csrf")
    csrf_token = existing_token or create_csrf_token(secret)
    response: HTMLResponse = request.app.state.templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={"csrf_token": csrf_token, "error": error},
        status_code=status_code,
    )
    if existing_token is None:
        response.set_cookie(
            "csrf",
            csrf_token,
            secure=settings.session_cookie_secure,
            httponly=True,
            samesite="lax",
        )
    return response


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: DbSession) -> Response:
    identity = optional_identity(request, db)
    if identity:
        destination = "/admin" if identity.is_admin else "/today"
        return RedirectResponse(destination, status_code=status.HTTP_303_SEE_OTHER)
    return login_response(request)


@router.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    db: DbSession,
    username: Annotated[str, Form(min_length=1, max_length=254)],
    password: Annotated[str, Form(min_length=1, max_length=1024)],
    csrf_token: Annotated[str, Form()],
) -> Response:
    settings = request.app.state.settings
    secret = settings.session_secret.get_secret_value()
    if not verify_csrf_token(request.cookies.get("csrf"), csrf_token, secret):
        return login_response(
            request, "요청이 만료되었습니다. 다시 시도해 주세요.", 403, rotate_csrf=True
        )

    key = client_key(request)
    if rate_limiter.is_limited(key):
        return login_response(request, "잠시 후 다시 시도해 주세요.", 429)

    clean_identifier = username.strip()
    username_matches = hmac.compare_digest(
        clean_identifier.encode(), settings.habit_tracker_username.encode()
    )
    admin_password_matches = verify_password(
        settings.habit_tracker_password_hash.get_secret_value(), password
    )
    member = db.scalar(
        select(User).where(User.normalized_email == clean_identifier.casefold())
    )
    member_password_matches = verify_password(
        (
            member.password_hash
            if member is not None
            else settings.habit_tracker_password_hash.get_secret_value()
        ),
        password,
    )
    role: str | None = None
    if username_matches and admin_password_matches:
        role = "admin"
    elif member is not None and member.is_active and member_password_matches:
        role = "member"
    if role is None:
        rate_limiter.record_failure(key)
        return login_response(request, "아이디 또는 비밀번호를 확인해 주세요.", 401)

    rate_limiter.clear(key)
    if member is not None and role == "member":
        member.last_login_at = datetime.now(UTC)
    try:
        token = create_session_token(
            settings, db, user=member if role == "member" else None, role=role
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        return login_response(request, "로그인하지 못했습니다. 다시 시도해 주세요.", 503)
    destination = "/admin" if role == "admin" else "/today"
    response = RedirectResponse(destination, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        "session",
        token,
        max_age=settings.session_ttl_hours * 3600,
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/logout")
def logout(
    request: Request,
    db: DbSession,
    csrf_token: Annotated[str, Form()],
) -> Response:
    settings = request.app.state.settings
    if not verify_csrf_token(
        request.cookies.get("csrf"), csrf_token, settings.session_secret.get_secret_value()
    ):
        return HTMLResponse("요청이 만료되었습니다.", status_code=403)
    revoke_session(db, request.cookies.get("session"))
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
    response = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(
        "session",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response
