import hmac
from typing import Annotated

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.auth.dependencies import optional_identity
from app.auth.rate_limit import LoginRateLimiter
from app.auth.security import (
    create_csrf_token,
    create_session_token,
    verify_csrf_token,
    verify_password,
)

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
def login_page(request: Request) -> Response:
    if optional_identity(request):
        return RedirectResponse("/today", status_code=status.HTTP_303_SEE_OTHER)
    return login_response(request)


@router.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    username: Annotated[str, Form(min_length=1, max_length=64)],
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

    username_matches = hmac.compare_digest(
        username.strip().encode(), settings.habit_tracker_username.encode()
    )
    password_matches = verify_password(
        settings.habit_tracker_password_hash.get_secret_value(), password
    )
    if not username_matches or not password_matches:
        rate_limiter.record_failure(key)
        return login_response(request, "아이디 또는 비밀번호를 확인해 주세요.", 401)

    rate_limiter.clear(key)
    response = RedirectResponse("/today", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        "session",
        create_session_token(settings),
        max_age=settings.session_ttl_hours * 3600,
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/logout")
def logout(
    request: Request,
    csrf_token: Annotated[str, Form()],
) -> Response:
    settings = request.app.state.settings
    if not verify_csrf_token(
        request.cookies.get("csrf"), csrf_token, settings.session_secret.get_secret_value()
    ):
        return HTMLResponse("요청이 만료되었습니다.", status_code=403)
    response = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(
        "session",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response
