from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.models import AppSettings, Habit, HabitCompletion, HabitSchedule, Reminder
from app.domain.schedules import (
    WEEKDAY_LABELS,
    ScheduleWindow,
    is_scheduled,
    mask_to_weekdays,
    schedule_for_date,
)
from app.domain.streaks import calculate_streak


@dataclass(frozen=True)
class TodayHabit:
    habit: Habit
    completed: bool
    streak: int
    schedule_label: str
    reminder_time_label: str | None
    reminder_enabled: bool


def compact_schedule_label(weekdays: tuple[int, ...]) -> str:
    if weekdays == tuple(range(7)):
        return "매일"
    if weekdays == tuple(range(5)):
        return "주중"
    if weekdays == (5, 6):
        return "주말"
    return "·".join(WEEKDAY_LABELS[weekday] for weekday in weekdays)


def twelve_hour_time_label(local_time: time) -> str:
    display_hour = local_time.hour % 12 or 12
    period = "AM" if local_time.hour < 12 else "PM"
    return f"{display_hour}:{local_time.minute:02d} {period}"


def habit_card_sort_key(completed: bool, habit: Habit) -> tuple[bool, bool, time, int]:
    reminder = habit.reminder
    return (
        completed,
        reminder is None,
        reminder.local_time if reminder is not None else time.max,
        habit.id,
    )


def application_timezone(db: Session) -> ZoneInfo:
    settings = db.get(AppSettings, 1)
    if settings is None:
        raise RuntimeError("Application settings are not initialized")
    return ZoneInfo(settings.timezone)


def current_local_date(db: Session, now: datetime | None = None) -> date:
    instant = now or datetime.now(UTC)
    return instant.astimezone(application_timezone(db)).date()


def schedule_windows(db: Session, habit_id: int) -> list[ScheduleWindow]:
    schedules = db.scalars(
        select(HabitSchedule)
        .where(HabitSchedule.habit_id == habit_id)
        .order_by(HabitSchedule.effective_from)
    ).all()
    return [
        ScheduleWindow(
            weekdays_mask=schedule.weekdays_mask,
            effective_from=schedule.effective_from,
            effective_until=schedule.effective_until,
        )
        for schedule in schedules
    ]


def effective_schedule(db: Session, habit_id: int, local_date: date) -> HabitSchedule | None:
    return db.scalar(
        select(HabitSchedule).where(
            HabitSchedule.habit_id == habit_id,
            HabitSchedule.effective_from <= local_date,
            (HabitSchedule.effective_until.is_(None))
            | (HabitSchedule.effective_until > local_date),
        )
    )


def latest_schedule(db: Session, habit_id: int) -> HabitSchedule | None:
    return db.scalar(
        select(HabitSchedule)
        .where(HabitSchedule.habit_id == habit_id)
        .order_by(HabitSchedule.effective_from.desc(), HabitSchedule.id.desc())
        .limit(1)
    )


def update_schedule(
    db: Session, habit: Habit, weekdays_mask: int, effective_date: date
) -> HabitSchedule:
    schedule = effective_schedule(db, habit.id, effective_date)
    if schedule is None:
        schedule = HabitSchedule(
            habit=habit,
            weekdays_mask=weekdays_mask,
            effective_from=effective_date,
        )
        db.add(schedule)
    elif schedule.effective_from == effective_date:
        schedule.weekdays_mask = weekdays_mask
    elif schedule.weekdays_mask != weekdays_mask:
        schedule.effective_until = effective_date
        schedule = HabitSchedule(
            habit=habit,
            weekdays_mask=weekdays_mask,
            effective_from=effective_date,
        )
        db.add(schedule)
    return schedule


def pause_schedule(db: Session, habit: Habit, archived_on: date) -> None:
    schedule = effective_schedule(db, habit.id, archived_on)
    if schedule is None:
        return
    inactive_from = archived_on + timedelta(days=1)
    if schedule.effective_until is None or schedule.effective_until > inactive_from:
        schedule.effective_until = inactive_from


def restart_habit(db: Session, habit: Habit, restarted_on: date) -> None:
    schedule = effective_schedule(db, habit.id, restarted_on)
    archived_at = habit.archived_at
    if archived_at is not None and archived_at.tzinfo is None:
        archived_at = archived_at.replace(tzinfo=UTC)
    archived_on = (
        archived_at.astimezone(application_timezone(db)).date()
        if archived_at is not None
        else None
    )
    if (
        schedule is not None
        and archived_on == restarted_on
        and schedule.effective_until == restarted_on + timedelta(days=1)
    ):
        schedule.effective_until = None
    if schedule is None:
        previous_schedule = latest_schedule(db, habit.id)
        if previous_schedule is None:
            raise ValueError("다시 시작할 수행 요일을 찾지 못했습니다.")
        schedule = update_schedule(
            db, habit, previous_schedule.weekdays_mask, restarted_on
        )
    habit.archived_at = None
    if habit.reminder is not None:
        habit.reminder.weekdays_mask = schedule.weekdays_mask
        habit.reminder.timezone = str(application_timezone(db))
        habit.reminder.is_enabled = habit.reminder.local_time is not None


def update_reminder(
    db: Session,
    habit: Habit,
    *,
    is_enabled: bool,
    weekdays_mask: int,
    local_time: time,
    timezone: str,
) -> Reminder:
    reminder = habit.reminder
    if reminder is None:
        reminder = Reminder(habit=habit)
        db.add(reminder)
    reminder.is_enabled = is_enabled
    reminder.weekdays_mask = weekdays_mask
    reminder.local_time = local_time
    reminder.timezone = timezone
    return reminder


def habit_streak(db: Session, habit_id: int, as_of: date) -> int:
    schedules = schedule_windows(db, habit_id)
    if not schedules:
        return 0
    first_date = min(schedule.effective_from for schedule in schedules)
    completions = set(
        db.scalars(
            select(HabitCompletion.local_date).where(
                HabitCompletion.habit_id == habit_id,
                HabitCompletion.local_date >= first_date,
                HabitCompletion.local_date <= as_of,
            )
        ).all()
    )
    return calculate_streak(as_of, schedules, completions)


def today_habits(db: Session, local_date: date) -> list[TodayHabit]:
    habits = db.scalars(
        select(Habit).where(Habit.archived_at.is_(None)).order_by(Habit.created_at, Habit.id)
    ).all()
    completed_ids = set(
        db.scalars(
            select(HabitCompletion.habit_id).where(HabitCompletion.local_date == local_date)
        ).all()
    )
    result: list[TodayHabit] = []
    for habit in habits:
        windows = schedule_windows(db, habit.id)
        window = schedule_for_date(windows, local_date)
        if window is None or not is_scheduled(window, local_date):
            continue
        reminder = habit.reminder
        completed = habit.id in completed_ids
        result.append(
            TodayHabit(
                habit=habit,
                completed=completed,
                streak=habit_streak(db, habit.id, local_date),
                schedule_label=compact_schedule_label(
                    mask_to_weekdays(window.weekdays_mask)
                ),
                reminder_time_label=(
                    twelve_hour_time_label(reminder.local_time)
                    if reminder is not None
                    else None
                ),
                reminder_enabled=reminder.is_enabled if reminder is not None else False,
            )
        )
    result.sort(key=lambda item: habit_card_sort_key(item.completed, item.habit))
    return result


def set_completion(db: Session, habit_id: int, local_date: date, completed: bool) -> None:
    if completed:
        statement = (
            sqlite_insert(HabitCompletion)
            .values(habit_id=habit_id, local_date=local_date)
            .on_conflict_do_nothing(index_elements=["habit_id", "local_date"])
        )
        db.execute(statement)
    else:
        db.execute(
            delete(HabitCompletion).where(
                HabitCompletion.habit_id == habit_id,
                HabitCompletion.local_date == local_date,
            )
        )
    db.commit()
