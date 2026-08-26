from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, timedelta

from app.domain.schedules import ScheduleWindow, is_scheduled, schedule_for_date


@dataclass(frozen=True)
class AchievementStats:
    total_count: int
    longest_streak: int
    current_streak: int


def calculate_achievement_stats(
    as_of: date,
    schedules: list[ScheduleWindow],
    completion_dates: Collection[date],
) -> AchievementStats:
    completions = {
        completion_date
        for completion_date in completion_dates
        if completion_date <= as_of
    }
    if not schedules:
        return AchievementStats(
            total_count=len(completions),
            longest_streak=0,
            current_streak=0,
        )

    first_schedule_date = min(schedule.effective_from for schedule in schedules)
    cursor = first_schedule_date
    current_streak = 0
    longest_streak = 0
    while cursor <= as_of:
        if cursor in completions:
            current_streak += 1
            longest_streak = max(longest_streak, current_streak)
        elif cursor != as_of and is_scheduled(
            schedule_for_date(schedules, cursor), cursor
        ):
            current_streak = 0
        cursor += timedelta(days=1)

    return AchievementStats(
        total_count=len(completions),
        longest_streak=longest_streak,
        current_streak=current_streak,
    )


def calculate_streak(
    as_of: date,
    schedules: list[ScheduleWindow],
    completion_dates: Collection[date],
) -> int:
    return calculate_achievement_stats(
        as_of, schedules, completion_dates
    ).current_streak
