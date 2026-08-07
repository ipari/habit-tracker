from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.accounts.service import cancel_invitation, create_invitation
from app.auth.dependencies import DbSession, MemberIdentity
from app.auth.security import password_hasher, revoke_user_sessions, verify_password
from app.db.models import AppSettings, Habit, Invitation, Reminder, User
from app.web import render_template, request_has_valid_csrf

router = APIRouter()

def validate_timezone(value: str) -> str:
    timezone = value.strip()
    if not timezone or len(timezone) > 64:
        raise ValueError("시간대를 1자 이상 64자 이하로 입력해 주세요.")
    try:
        ZoneInfo(timezone)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("올바른 IANA 시간대를 입력해 주세요.") from exc
    return timezone


def settings_context(
    identity: object,
    timezone: str,
    *,
    error: str | None = None,
    saved: bool = False,
    invitation: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "user": identity,
        "timezone": timezone,
        "timezone_error": error,
        "timezone_saved": saved,
        "invitation": invitation,
    }


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request, db: DbSession, identity: MemberIdentity
) -> HTMLResponse:
    assert identity.user_id is not None
    app_settings = db.scalar(
        select(AppSettings).where(AppSettings.user_id == identity.user_id)
    )
    timezone = app_settings.timezone if app_settings else "UTC"
    invitation = db.scalar(
        select(Invitation)
        .where(
            Invitation.created_by_user_id == identity.user_id,
            Invitation.is_active.is_(True),
        )
        .order_by(Invitation.created_at.desc(), Invitation.id.desc())
        .limit(1)
    )
    invitation_row = (
        {
            "invitation": invitation,
            "url": str(request.url_for("signup_page", code=invitation.code)),
            "joined_count": db.scalar(
                select(func.count(User.id)).where(User.invitation_id == invitation.id)
            )
            or 0,
        }
        if invitation is not None
        else None
    )
    return render_template(
        request,
        "settings.html",
        settings_context(
            identity,
            timezone,
            saved=request.query_params.get("saved") == "timezone",
            invitation=invitation_row,
        ),
    )


@router.post("/settings/timezone", response_class=HTMLResponse)
def update_timezone(
    request: Request,
    db: DbSession,
    identity: MemberIdentity,
    timezone: Annotated[str, Form(max_length=64)],
    csrf_token: Annotated[str, Form()],
) -> Response:
    assert identity.user_id is not None
    if not request_has_valid_csrf(request, csrf_token):
        return render_template(
            request,
            "settings.html",
            settings_context(identity, timezone, error="요청이 만료되었습니다."),
            403,
        )
    try:
        validated_timezone = validate_timezone(timezone)
        app_settings = db.scalar(
            select(AppSettings).where(AppSettings.user_id == identity.user_id)
        )
        if app_settings is None:
            app_settings = AppSettings(
                user_id=identity.user_id, timezone=validated_timezone
            )
            db.add(app_settings)
        else:
            app_settings.timezone = validated_timezone
        for reminder in db.scalars(
            select(Reminder)
            .join(Reminder.habit)
            .where(Habit.user_id == identity.user_id)
        ).all():
            reminder.timezone = validated_timezone
        db.commit()
    except ValueError as exc:
        db.rollback()
        return render_template(
            request,
            "settings.html",
            settings_context(identity, timezone, error=str(exc)),
            422,
        )
    except SQLAlchemyError:
        db.rollback()
        return render_template(
            request,
            "settings.html",
            settings_context(
                identity,
                timezone,
                error="시간대를 저장하지 못했습니다. 다시 시도해 주세요.",
            ),
            503,
        )
    return RedirectResponse(
        "/settings?saved=timezone", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/settings/invitations")
def create_member_invitation(
    request: Request,
    db: DbSession,
    identity: MemberIdentity,
    csrf_token: Annotated[str, Form()],
) -> Response:
    if not request_has_valid_csrf(request, csrf_token):
        return HTMLResponse("요청이 만료되었습니다.", status_code=403)
    assert identity.user_id is not None
    try:
        create_invitation(db, creator_user_id=identity.user_id)
        db.commit()
    except (SQLAlchemyError, RuntimeError):
        db.rollback()
        return HTMLResponse("초대 링크를 만들지 못했습니다.", status_code=503)
    return RedirectResponse("/settings", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/settings/invitations/{invitation_id}/cancel")
def cancel_member_invitation(
    invitation_id: int,
    request: Request,
    db: DbSession,
    identity: MemberIdentity,
    csrf_token: Annotated[str, Form()],
) -> Response:
    if not request_has_valid_csrf(request, csrf_token):
        return HTMLResponse("요청이 만료되었습니다.", status_code=403)
    assert identity.user_id is not None
    invitation = db.scalar(
        select(Invitation).where(
            Invitation.id == invitation_id,
            Invitation.created_by_user_id == identity.user_id,
        )
    )
    if invitation is None:
        return HTMLResponse("초대 링크를 찾을 수 없습니다.", status_code=404)
    cancel_invitation(invitation)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        return HTMLResponse("초대를 취소하지 못했습니다.", status_code=503)
    return RedirectResponse("/settings", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/settings/password")
def change_member_password(
    request: Request,
    db: DbSession,
    identity: MemberIdentity,
    current_password: Annotated[str, Form(max_length=1024)],
    new_password: Annotated[str, Form(max_length=1024)],
    new_password_confirmation: Annotated[str, Form(max_length=1024)],
    csrf_token: Annotated[str, Form()],
) -> Response:
    if not request_has_valid_csrf(request, csrf_token):
        return HTMLResponse("요청이 만료되었습니다.", status_code=403)
    assert identity.user_id is not None
    user = db.get(User, identity.user_id)
    if user is None or not verify_password(user.password_hash, current_password):
        return HTMLResponse("현재 비밀번호를 확인해 주세요.", status_code=422)
    if len(new_password) < 8 or new_password != new_password_confirmation:
        return HTMLResponse("새 비밀번호와 확인을 올바르게 입력해 주세요.", status_code=422)
    try:
        user.password_hash = password_hasher.hash(new_password)
        revoke_user_sessions(db, user.id)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        return HTMLResponse("비밀번호를 변경하지 못했습니다.", status_code=503)
    response = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(
        "session",
        secure=request.app.state.settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response
