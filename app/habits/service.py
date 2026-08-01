from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.models import AppSettings, Habit, HabitCompletion, HabitSchedule, Reminder
from app.domain.schedules import ScheduleWindow, is_scheduled, schedule_for_date
from app.domain.streaks import calculate_streak


@dataclass(frozen=True)
class TodayHabit:
    habit: Habit
    completed: bool
    streak: int


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
        if not is_scheduled(schedule_for_date(windows, local_date), local_date):
            continue
        result.append(
            TodayHabit(
                habit=habit,
                completed=habit.id in completed_ids,
                streak=habit_streak(db, habit.id, local_date),
            )
        )
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
