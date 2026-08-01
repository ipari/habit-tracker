import calendar
from dataclasses import dataclass
from datetime import UTC, date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Habit, HabitCompletion, HabitSchedule
from app.domain.schedules import (
    ScheduleWindow,
    is_scheduled,
    mask_to_weekdays,
    schedule_for_date,
)
from app.habits.service import (
    application_timezone,
    compact_schedule_label,
    habit_card_sort_key,
    habit_streak,
    twelve_hour_time_label,
)

WEEKDAY_HEADERS = ("월", "화", "수", "목", "금", "토", "일")


@dataclass(frozen=True)
class CalendarDay:
    local_date: date
    in_month: bool
    is_today: bool
    is_selected: bool
    is_future: bool
    scheduled_count: int
    completed_count: int
    extra_count: int
    state: str
    status_text: str


@dataclass(frozen=True)
class CalendarHabit:
    habit: Habit
    scheduled: bool
    completed: bool
    status_text: str
    streak: int
    schedule_label: str
    reminder_time_label: str | None
    reminder_enabled: bool


@dataclass(frozen=True)
class CalendarView:
    month_start: date
    month_label: str
    previous_month: date
    next_month: date
    weeks: list[list[CalendarDay]]
    selected_date: date
    selected_label: str
    selected_is_future: bool
    habits: list[CalendarHabit]
    additional_habits: list[CalendarHabit]


def shift_month(month_start: date, months: int) -> date:
    absolute_month = month_start.year * 12 + month_start.month - 1 + months
    year, zero_based_month = divmod(absolute_month, 12)
    return date(year, zero_based_month + 1, 1)


def month_dates(month_start: date) -> list[list[date]]:
    return calendar.Calendar(firstweekday=0).monthdatescalendar(
        month_start.year, month_start.month
    )


def _schedule_map(db: Session) -> dict[int, list[ScheduleWindow]]:
    schedules = db.scalars(
        select(HabitSchedule).order_by(HabitSchedule.habit_id, HabitSchedule.effective_from)
    ).all()
    result: dict[int, list[ScheduleWindow]] = {}
    for schedule in schedules:
        result.setdefault(schedule.habit_id, []).append(
            ScheduleWindow(
                weekdays_mask=schedule.weekdays_mask,
                effective_from=schedule.effective_from,
                effective_until=schedule.effective_until,
            )
        )
    return result


def _habit_visible_on(db: Session, habit: Habit, local_date: date) -> bool:
    if habit.archived_at is None:
        return True
    archived_at = habit.archived_at
    if archived_at.tzinfo is None:
        archived_at = archived_at.replace(tzinfo=UTC)
    archived_on = archived_at.astimezone(application_timezone(db)).date()
    return local_date < archived_on


def _day_status(
    local_date: date,
    today: date,
    scheduled_count: int,
    scheduled_completed: int,
    extra_count: int,
) -> tuple[str, str]:
    completed_count = scheduled_completed + extra_count
    if local_date > today:
        status = "미래 날짜"
        if scheduled_count:
            status += f", 예정 {scheduled_count}개"
        return "future", status
    if scheduled_count == 0 and extra_count == 0:
        return "empty", "예정이나 기록 없음"
    parts: list[str] = []
    if scheduled_count:
        parts.append(f"예정 {scheduled_count}개 중 {scheduled_completed}개 완료")
    if extra_count:
        parts.append(f"추가 달성 {extra_count}개")
    if scheduled_count and scheduled_completed == scheduled_count:
        return "complete", ", ".join(parts)
    if completed_count:
        return "partial", ", ".join(parts)
    if local_date == today:
        return "planned", ", ".join(parts)
    return "missed", ", ".join(parts)


def build_calendar_view(
    db: Session,
    month_start: date,
    selected_date: date,
    today: date,
) -> CalendarView:
    raw_weeks = month_dates(month_start)
    grid_start, grid_end = raw_weeks[0][0], raw_weeks[-1][-1]
    habits = db.scalars(select(Habit).order_by(Habit.created_at, Habit.id)).all()
    schedules = _schedule_map(db)
    completion_rows = db.execute(
        select(HabitCompletion.habit_id, HabitCompletion.local_date).where(
            HabitCompletion.local_date >= grid_start,
            HabitCompletion.local_date <= grid_end,
        )
    ).all()
    completions = {(habit_id, local_date) for habit_id, local_date in completion_rows}

    weeks: list[list[CalendarDay]] = []
    for raw_week in raw_weeks:
        week: list[CalendarDay] = []
        for local_date in raw_week:
            scheduled_count = 0
            scheduled_completed = 0
            extra_count = 0
            for habit in habits:
                window = schedule_for_date(schedules.get(habit.id, []), local_date)
                if window is None or not _habit_visible_on(db, habit, local_date):
                    continue
                completed = (habit.id, local_date) in completions
                scheduled = is_scheduled(window, local_date)
                if scheduled:
                    scheduled_count += 1
                    scheduled_completed += int(completed)
                elif completed:
                    extra_count += 1
            state, status_text = _day_status(
                local_date, today, scheduled_count, scheduled_completed, extra_count
            )
            week.append(
                CalendarDay(
                    local_date=local_date,
                    in_month=local_date.month == month_start.month,
                    is_today=local_date == today,
                    is_selected=local_date == selected_date,
                    is_future=local_date > today,
                    scheduled_count=scheduled_count,
                    completed_count=scheduled_completed,
                    extra_count=extra_count,
                    state=state,
                    status_text=status_text,
                )
            )
        weeks.append(week)

    selected_habits: list[CalendarHabit] = []
    additional_habits: list[CalendarHabit] = []
    for habit in habits:
        window = schedule_for_date(schedules.get(habit.id, []), selected_date)
        if window is None or not _habit_visible_on(db, habit, selected_date):
            continue
        completed = (habit.id, selected_date) in completions
        scheduled = is_scheduled(window, selected_date)
        if completed and scheduled:
            status_text = "예정일 달성"
        elif completed:
            status_text = "추가 달성"
        elif selected_date > today:
            status_text = "예정일 · 미래 날짜" if scheduled else "비예정일 · 미래 날짜"
        elif scheduled and selected_date == today:
            status_text = "오늘 예정 · 미완료"
        elif scheduled:
            status_text = "예정일 미달성"
        else:
            status_text = "비예정일 미기록"
        item = CalendarHabit(
            habit=habit,
            scheduled=scheduled,
            completed=completed,
            status_text=status_text,
            streak=habit_streak(db, habit.id, today),
            schedule_label=compact_schedule_label(
                mask_to_weekdays(window.weekdays_mask)
            ),
            reminder_time_label=(
                twelve_hour_time_label(habit.reminder.local_time)
                if habit.reminder is not None
                else None
            ),
            reminder_enabled=(
                habit.reminder.is_enabled if habit.reminder is not None else False
            ),
        )
        if scheduled or completed:
            selected_habits.append(item)
        elif selected_date <= today:
            additional_habits.append(item)
    selected_habits.sort(
        key=lambda item: habit_card_sort_key(item.completed, item.habit)
    )
    additional_habits.sort(
        key=lambda item: habit_card_sort_key(item.completed, item.habit)
    )

    weekday = WEEKDAY_HEADERS[selected_date.weekday()]
    return CalendarView(
        month_start=month_start,
        month_label=f"{month_start.year}년 {month_start.month}월",
        previous_month=shift_month(month_start, -1),
        next_month=shift_month(month_start, 1),
        weeks=weeks,
        selected_date=selected_date,
        selected_label=(
            f"{selected_date.year}년 {selected_date.month}월 {selected_date.day}일 {weekday}요일"
        ),
        selected_is_future=selected_date > today,
        habits=selected_habits,
        additional_habits=additional_habits,
    )
