from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Annotated, Any

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.auth.dependencies import CurrentIdentity, DbSession
from app.db.models import Habit, Reminder
from app.domain.schedules import WEEKDAY_LABELS, mask_to_weekdays, weekdays_to_mask
from app.habits.service import (
    application_timezone,
    compact_schedule_label,
    current_local_date,
    effective_schedule,
    habit_streak,
    set_completion,
    today_habits,
    twelve_hour_time_label,
    update_reminder,
    update_schedule,
)
from app.web import render_template, request_has_valid_csrf

router = APIRouter()
BACKGROUND_PRESETS = (
    "dawn",
    "forest",
    "ocean",
    "sunset",
    "lavender",
    "citrus",
    "midnight",
    "rose",
    "sky",
    "stone",
)


@dataclass(frozen=True)
class HabitListItem:
    habit: Habit
    streak: int
    schedule_label: str
    reminder_time_label: str | None
    reminder_enabled: bool


def habit_or_404(db: DbSession, habit_id: int) -> Habit:
    habit = db.get(Habit, habit_id)
    if habit is None:
        raise HTTPException(status_code=404, detail="Habit not found")
    return habit


def date_label(local_date: date) -> str:
    weekday = WEEKDAY_LABELS[local_date.weekday()]
    return f"{local_date.year}년 {local_date.month}월 {local_date.day}일 {weekday}요일"


def normalize_return_to(value: str | None) -> str:
    return "today" if value == "today" else "habits"


def return_path(value: str | None) -> str:
    return "/today" if normalize_return_to(value) == "today" else "/habits"


def habit_list_item(db: DbSession, habit: Habit, local_date: date) -> HabitListItem:
    schedule = effective_schedule(db, habit.id, local_date)
    weekdays = mask_to_weekdays(schedule.weekdays_mask) if schedule else ()
    reminder = habit.reminder
    return HabitListItem(
        habit=habit,
        streak=habit_streak(db, habit.id, local_date),
        schedule_label=compact_schedule_label(weekdays),
        reminder_time_label=(
            twelve_hour_time_label(reminder.local_time) if reminder is not None else None
        ),
        reminder_enabled=reminder.is_enabled if reminder is not None else False,
    )


def form_context(
    *,
    habit: Habit | None = None,
    reminder: Reminder | None = None,
    selected_weekdays: tuple[int, ...] = tuple(range(7)),
    reminder_timezone: str = "UTC",
    return_to: str = "habits",
    values: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    resolved_values = values or {}
    reminder_time = reminder.local_time.strftime("%H:%M") if reminder else "09:00"
    return {
        "habit": habit,
        "reminder": reminder,
        "selected_weekdays": selected_weekdays,
        "reminder_enabled": resolved_values.get(
            "reminder_enabled", reminder.is_enabled if reminder else False
        ),
        "reminder_time": resolved_values.get("reminder_time", reminder_time),
        "reminder_timezone": reminder.timezone if reminder else reminder_timezone,
        "return_to": normalize_return_to(return_to),
        "return_path": return_path(return_to),
        "return_label": "오늘" if normalize_return_to(return_to) == "today" else "습관",
        "weekday_labels": WEEKDAY_LABELS,
        "background_presets": BACKGROUND_PRESETS,
        "values": resolved_values,
        "error": error,
    }


def validate_habit_form(
    name: str,
    emoji: str,
    weekdays: list[int] | None,
    background_preset: str,
) -> tuple[str, str, int]:
    clean_name = name.strip()
    clean_emoji = emoji.strip()
    if not clean_name or len(clean_name) > 80:
        raise ValueError("습관 이름을 1자 이상 80자 이하로 입력해 주세요.")
    if len(clean_emoji) > 32:
        raise ValueError("이모지는 32자 이하로 입력해 주세요.")
    if background_preset not in BACKGROUND_PRESETS:
        raise ValueError("올바른 배경을 선택해 주세요.")
    try:
        mask = weekdays_to_mask(weekdays or [])
    except ValueError as exc:
        raise ValueError("수행 요일을 하나 이상 선택해 주세요.") from exc
    return clean_name, clean_emoji, mask


def validate_reminder_form(
    *,
    reminder_time: str,
) -> time:
    try:
        if len(reminder_time) != 5 or reminder_time[2] != ":":
            raise ValueError
        local_time = time.fromisoformat(reminder_time)
    except ValueError as exc:
        raise ValueError("알림 시간을 올바르게 입력해 주세요.") from exc

    return local_time


@router.get("/today", response_class=HTMLResponse)
def today(request: Request, db: DbSession, identity: CurrentIdentity) -> HTMLResponse:
    local_date = current_local_date(db)
    return render_template(
        request,
        "today.html",
        {
            "user": identity,
            "local_date": local_date,
            "date_label": date_label(local_date),
            "habits": today_habits(db, local_date),
            "save_error": request.query_params.get("save_error") == "1",
        },
    )


@router.get("/habits", response_class=HTMLResponse)
def list_habits(
    request: Request, db: DbSession, _identity: CurrentIdentity
) -> HTMLResponse:
    local_date = current_local_date(db)
    habits = db.scalars(
        select(Habit).order_by(Habit.archived_at.is_not(None), Habit.created_at, Habit.id)
    ).all()
    active_habits: list[HabitListItem] = []
    archived_habits: list[HabitListItem] = []
    for habit in habits:
        item = habit_list_item(db, habit, local_date)
        if habit.archived_at is None:
            active_habits.append(item)
        else:
            archived_habits.append(item)
    return render_template(
        request,
        "habits/index.html",
        {
            "active_habits": active_habits,
            "archived_habits": archived_habits,
        },
    )


@router.get("/habits/new", response_class=HTMLResponse)
def new_habit(
    request: Request, db: DbSession, _identity: CurrentIdentity
) -> HTMLResponse:
    return render_template(
        request,
        "habits/form.html",
        form_context(reminder_timezone=str(application_timezone(db))),
    )


@router.get("/habits/{habit_id}", response_class=HTMLResponse)
def habit_detail(
    habit_id: int, request: Request, db: DbSession, _identity: CurrentIdentity
) -> HTMLResponse:
    habit = habit_or_404(db, habit_id)
    local_date = current_local_date(db)
    schedule = effective_schedule(db, habit.id, local_date)
    weekdays = mask_to_weekdays(schedule.weekdays_mask) if schedule else ()
    schedule_label = (
        "매일"
        if len(weekdays) == 7
        else " · ".join(f"{WEEKDAY_LABELS[weekday]}요일" for weekday in weekdays)
    )
    reminder = habit.reminder
    origin = normalize_return_to(request.query_params.get("from"))
    reminder_label = "사용 안 함"
    if reminder is not None and reminder.is_enabled:
        reminder_label = f"{reminder.local_time.strftime('%H:%M')} · {reminder.timezone}"
    return render_template(
        request,
        "habits/detail.html",
        {
            "habit": habit,
            "streak": habit_streak(db, habit.id, local_date),
            "schedule_label": schedule_label,
            "reminder_label": reminder_label,
            "return_to": origin,
            "return_path": return_path(origin),
            "return_label": "오늘" if origin == "today" else "습관",
        },
    )


@router.post("/habits", response_class=HTMLResponse)
def create_habit(
    request: Request,
    db: DbSession,
    _identity: CurrentIdentity,
    name: Annotated[str, Form(max_length=80)],
    background_preset: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
    emoji: Annotated[str, Form(max_length=32)] = "",
    weekdays: Annotated[list[int] | None, Form()] = None,
    reminder_enabled: Annotated[bool, Form()] = False,
    reminder_time: Annotated[str, Form(max_length=5)] = "09:00",
) -> Response:
    selected = tuple(weekdays or ())
    timezone = str(application_timezone(db))
    values = {
        "name": name,
        "emoji": emoji,
        "background_preset": background_preset,
        "reminder_enabled": reminder_enabled,
        "reminder_time": reminder_time,
    }
    if not request_has_valid_csrf(request, csrf_token):
        return render_template(
            request,
            "habits/form.html",
            form_context(
                selected_weekdays=selected,
                reminder_timezone=timezone,
                values=values,
                error="요청이 만료되었습니다.",
            ),
            403,
        )
    try:
        clean_name, clean_emoji, mask = validate_habit_form(
            name, emoji, weekdays, background_preset
        )
        local_time = validate_reminder_form(reminder_time=reminder_time)
        local_date = current_local_date(db)
        habit = Habit(
            name=clean_name,
            emoji=clean_emoji,
            background_preset=background_preset,
        )
        db.add(habit)
        update_schedule(db, habit, mask, local_date)
        update_reminder(
            db,
            habit,
            is_enabled=reminder_enabled and habit.archived_at is None,
            weekdays_mask=mask,
            local_time=local_time,
            timezone=timezone,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        return render_template(
            request,
            "habits/form.html",
            form_context(
                selected_weekdays=selected,
                reminder_timezone=timezone,
                values=values,
                error=str(exc),
            ),
            422,
        )
    except SQLAlchemyError:
        db.rollback()
        return render_template(
            request,
            "habits/form.html",
            form_context(
                selected_weekdays=selected,
                reminder_timezone=timezone,
                values=values,
                error="저장하지 못했습니다. 다시 시도해 주세요.",
            ),
            503,
        )
    return RedirectResponse("/today", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/habits/{habit_id}/edit", response_class=HTMLResponse)
def edit_habit(
    habit_id: int, request: Request, db: DbSession, _identity: CurrentIdentity
) -> HTMLResponse:
    habit = habit_or_404(db, habit_id)
    local_date = current_local_date(db)
    schedule = effective_schedule(db, habit.id, local_date)
    selected = mask_to_weekdays(schedule.weekdays_mask) if schedule else ()
    reminder = habit.reminder
    origin = normalize_return_to(request.query_params.get("from"))
    return render_template(
        request,
        "habits/form.html",
        form_context(
            habit=habit,
            reminder=reminder,
            selected_weekdays=selected,
            reminder_timezone=str(application_timezone(db)),
            return_to=origin,
        ),
    )


@router.get("/habits/{habit_id}/share", response_class=HTMLResponse)
def share_habit(
    habit_id: int, request: Request, db: DbSession, _identity: CurrentIdentity
) -> HTMLResponse:
    habit = habit_or_404(db, habit_id)
    local_date = current_local_date(db)
    origin = normalize_return_to(request.query_params.get("from"))
    return render_template(
        request,
        "habits/share.html",
        {
            "habit": habit,
            "share_emoji": habit.emoji or "✨",
            "streak": habit_streak(db, habit.id, local_date),
            "return_to": origin,
        },
    )


@router.post("/habits/{habit_id}", response_class=HTMLResponse)
def save_habit(
    habit_id: int,
    request: Request,
    db: DbSession,
    _identity: CurrentIdentity,
    name: Annotated[str, Form(max_length=80)],
    background_preset: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
    emoji: Annotated[str, Form(max_length=32)] = "",
    weekdays: Annotated[list[int] | None, Form()] = None,
    reminder_enabled: Annotated[bool, Form()] = False,
    reminder_time: Annotated[str, Form(max_length=5)] = "09:00",
    return_to: Annotated[str, Form(max_length=16)] = "habits",
) -> Response:
    habit = habit_or_404(db, habit_id)
    reminder = habit.reminder
    selected = tuple(weekdays or ())
    timezone = reminder.timezone if reminder else str(application_timezone(db))
    origin = normalize_return_to(return_to)
    values = {
        "name": name,
        "emoji": emoji,
        "background_preset": background_preset,
        "reminder_enabled": reminder_enabled,
        "reminder_time": reminder_time,
    }
    if not request_has_valid_csrf(request, csrf_token):
        return render_template(
            request,
            "habits/form.html",
            form_context(
                habit=habit,
                reminder=reminder,
                selected_weekdays=selected,
                reminder_timezone=timezone,
                return_to=origin,
                values=values,
                error="요청이 만료되었습니다.",
            ),
            403,
        )
    try:
        clean_name, clean_emoji, mask = validate_habit_form(
            name, emoji, weekdays, background_preset
        )
        local_time = validate_reminder_form(reminder_time=reminder_time)
        habit.name = clean_name
        habit.emoji = clean_emoji
        habit.background_preset = background_preset
        update_schedule(db, habit, mask, current_local_date(db))
        update_reminder(
            db,
            habit,
            is_enabled=reminder_enabled and habit.archived_at is None,
            weekdays_mask=mask,
            local_time=local_time,
            timezone=timezone,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        return render_template(
            request,
            "habits/form.html",
            form_context(
                habit=habit,
                reminder=reminder,
                selected_weekdays=selected,
                reminder_timezone=timezone,
                return_to=origin,
                values=values,
                error=str(exc),
            ),
            422,
        )
    except SQLAlchemyError:
        db.rollback()
        return render_template(
            request,
            "habits/form.html",
            form_context(
                habit=habit,
                reminder=reminder,
                selected_weekdays=selected,
                reminder_timezone=timezone,
                return_to=origin,
                values=values,
                error="저장하지 못했습니다. 다시 시도해 주세요.",
            ),
            503,
        )
    return RedirectResponse(return_path(origin), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/habits/{habit_id}/archive")
def archive_habit(
    habit_id: int,
    request: Request,
    db: DbSession,
    _identity: CurrentIdentity,
    csrf_token: Annotated[str, Form()],
) -> Response:
    if not request_has_valid_csrf(request, csrf_token):
        return HTMLResponse("요청이 만료되었습니다.", status_code=403)
    habit = habit_or_404(db, habit_id)
    habit.archived_at = datetime.now(UTC)
    if habit.reminder is not None:
        habit.reminder.is_enabled = False
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        return HTMLResponse("보관하지 못했습니다. 다시 시도해 주세요.", status_code=503)
    return RedirectResponse(f"/habits/{habit.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/habits/{habit_id}/completions/{local_date}")
def change_completion(
    habit_id: int,
    local_date: date,
    request: Request,
    db: DbSession,
    _identity: CurrentIdentity,
    completed: Annotated[bool, Form()],
    csrf_token: Annotated[str, Form()],
) -> Response:
    if not request_has_valid_csrf(request, csrf_token):
        return HTMLResponse("요청이 만료되었습니다.", status_code=403)
    habit = habit_or_404(db, habit_id)
    today = current_local_date(db)
    if local_date > today:
        raise HTTPException(status_code=400, detail="Future completions are not allowed")
    try:
        set_completion(db, habit.id, local_date, completed)
    except SQLAlchemyError:
        db.rollback()
        if request.headers.get("HX-Request") == "true":
            return HTMLResponse(
                "저장하지 못했습니다. 다시 시도해 주세요.",
                status_code=503,
                headers={"HX-Retarget": "#sync-error", "HX-Reswap": "innerHTML"},
            )
        return RedirectResponse("/today?save_error=1", status_code=303)
    if request.headers.get("HX-Request") == "true" and local_date == today:
        return render_template(
            request,
            "habits/_today_list.html",
            {"habits": today_habits(db, today), "local_date": today},
        )
    return RedirectResponse("/today", status_code=status.HTTP_303_SEE_OTHER)
