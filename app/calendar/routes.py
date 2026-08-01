from datetime import date
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.exc import SQLAlchemyError

from app.auth.dependencies import CurrentIdentity, DbSession
from app.calendar.service import CalendarView, build_calendar_view
from app.db.models import Habit
from app.habits.service import current_local_date, set_completion
from app.web import render_template, request_has_valid_csrf

router = APIRouter()


def parse_month(value: str | None, today: date) -> date:
    if value is None:
        return date(today.year, today.month, 1)
    try:
        parsed = date.fromisoformat(f"{value}-01")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid calendar month") from exc
    return parsed


def parse_selected(value: str | None, month_start: date, today: date) -> date:
    if value is None:
        current_month = (today.year, today.month) == (month_start.year, month_start.month)
        return today if current_month else month_start
    try:
        selected = date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid selected date") from exc
    if (selected.year, selected.month) != (month_start.year, month_start.month):
        return month_start
    return selected


def calendar_context(view: CalendarView, save_error: bool = False) -> dict[str, object]:
    return {
        "calendar": view,
        "weekday_headers": ("월", "화", "수", "목", "금", "토", "일"),
        "save_error": save_error,
    }


def render_calendar(
    request: Request,
    db: DbSession,
    month: str | None,
    selected: str | None,
    *,
    fragment: bool,
) -> HTMLResponse:
    today = current_local_date(db)
    month_start = parse_month(month, today)
    selected_date = parse_selected(selected, month_start, today)
    view = build_calendar_view(db, month_start, selected_date, today)
    template = "calendar/_content.html" if fragment else "calendar/index.html"
    return render_template(
        request,
        template,
        calendar_context(view, request.query_params.get("save_error") == "1"),
    )


@router.get("/calendar", response_class=HTMLResponse)
def calendar_page(
    request: Request,
    db: DbSession,
    _identity: CurrentIdentity,
    month: str | None = None,
    selected: str | None = None,
) -> HTMLResponse:
    return render_calendar(
        request,
        db,
        month,
        selected,
        fragment=request.headers.get("HX-Request") == "true",
    )


@router.post("/calendar/habits/{habit_id}/completions/{local_date}")
def change_calendar_completion(
    habit_id: int,
    local_date: date,
    request: Request,
    db: DbSession,
    _identity: CurrentIdentity,
    completed: Annotated[bool, Form()],
    csrf_token: Annotated[str, Form()],
    month: Annotated[str, Form()],
) -> Response:
    if not request_has_valid_csrf(request, csrf_token):
        return HTMLResponse("요청이 만료되었습니다.", status_code=403)
    if db.get(Habit, habit_id) is None:
        raise HTTPException(status_code=404, detail="Habit not found")
    today = current_local_date(db)
    if local_date > today:
        raise HTTPException(status_code=400, detail="Future completions are not allowed")
    try:
        set_completion(db, habit_id, local_date, completed)
    except SQLAlchemyError:
        db.rollback()
        if request.headers.get("HX-Request") == "true":
            return HTMLResponse(
                "저장하지 못했습니다. 다시 시도해 주세요.",
                status_code=503,
                headers={"HX-Retarget": "#calendar-sync-error", "HX-Reswap": "innerHTML"},
            )
        return RedirectResponse(
            f"/calendar?month={month}&selected={local_date.isoformat()}&save_error=1",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    if request.headers.get("HX-Request") == "true":
        return render_calendar(
            request,
            db,
            month,
            local_date.isoformat(),
            fragment=True,
        )
    return RedirectResponse(
        f"/calendar?month={month}&selected={local_date.isoformat()}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
