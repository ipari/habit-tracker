from collections.abc import Collection
from datetime import date, timedelta

from app.domain.schedules import ScheduleWindow, is_scheduled, schedule_for_date


def calculate_streak(
    as_of: date,
    schedules: list[ScheduleWindow],
    completion_dates: Collection[date],
) -> int:
    if not schedules:
        return 0
    cursor = as_of
    first_schedule_date = min(schedule.effective_from for schedule in schedules)
    streak = 0
    while cursor >= first_schedule_date:
        if cursor in completion_dates:
            streak += 1
        elif cursor != as_of and is_scheduled(schedule_for_date(schedules, cursor), cursor):
            break
        cursor -= timedelta(days=1)
    return streak
