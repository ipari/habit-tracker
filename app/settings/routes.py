from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.auth.dependencies import CurrentIdentity, DbSession
from app.db.models import AppSettings, Reminder
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
) -> dict[str, object]:
    return {
        "user": identity,
        "timezone": timezone,
        "timezone_error": error,
        "timezone_saved": saved,
    }


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request, db: DbSession, identity: CurrentIdentity
) -> HTMLResponse:
    app_settings = db.get(AppSettings, 1)
    timezone = app_settings.timezone if app_settings else "UTC"
    return render_template(
        request,
        "settings.html",
        settings_context(
            identity,
            timezone,
            saved=request.query_params.get("saved") == "timezone",
        ),
    )


@router.post("/settings/timezone", response_class=HTMLResponse)
def update_timezone(
    request: Request,
    db: DbSession,
    identity: CurrentIdentity,
    timezone: Annotated[str, Form(max_length=64)],
    csrf_token: Annotated[str, Form()],
) -> Response:
    if not request_has_valid_csrf(request, csrf_token):
        return render_template(
            request,
            "settings.html",
            settings_context(identity, timezone, error="요청이 만료되었습니다."),
            403,
        )
    try:
        validated_timezone = validate_timezone(timezone)
        app_settings = db.get(AppSettings, 1)
        if app_settings is None:
            app_settings = AppSettings(id=1, timezone=validated_timezone)
            db.add(app_settings)
        else:
            app_settings.timezone = validated_timezone
        for reminder in db.scalars(select(Reminder)).all():
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
