from datetime import date

from app.domain.schedules import ScheduleWindow, weekdays_to_mask
from app.domain.streaks import calculate_streak

ALL_DAYS = weekdays_to_mask(list(range(7)))
MON_WED_FRI = weekdays_to_mask([0, 2, 4])
TUE_THU_SAT = weekdays_to_mask([1, 3, 5])


def test_unfinished_scheduled_today_does_not_break_streak() -> None:
    schedules = [ScheduleWindow(ALL_DAYS, date(2026, 1, 1))]
    completions = {date(2026, 1, 1), date(2026, 1, 2)}
    assert calculate_streak(date(2026, 1, 3), schedules, completions) == 2


def test_missed_past_scheduled_day_breaks_streak() -> None:
    schedules = [ScheduleWindow(ALL_DAYS, date(2026, 1, 1))]
    completions = {date(2026, 1, 1), date(2026, 1, 3)}
    assert calculate_streak(date(2026, 1, 3), schedules, completions) == 1


def test_extra_completion_counts_and_unscheduled_gap_is_skipped() -> None:
    schedules = [ScheduleWindow(MON_WED_FRI, date(2026, 1, 5))]
    monday = date(2026, 1, 5)
    tuesday = date(2026, 1, 6)
    wednesday = date(2026, 1, 7)
    assert calculate_streak(wednesday, schedules, {monday, tuesday, wednesday}) == 3
    assert calculate_streak(wednesday, schedules, {monday, wednesday}) == 2


def test_schedule_change_preserves_history_and_continues_streak() -> None:
    schedules = [
        ScheduleWindow(MON_WED_FRI, date(2026, 1, 1), date(2026, 1, 8)),
        ScheduleWindow(TUE_THU_SAT, date(2026, 1, 8)),
    ]
    completions = {date(2026, 1, 5), date(2026, 1, 7), date(2026, 1, 8)}
    assert calculate_streak(date(2026, 1, 8), schedules, completions) == 3


def test_streak_crosses_year_and_leap_day() -> None:
    schedules = [ScheduleWindow(ALL_DAYS, date(2024, 2, 28))]
    leap_completions = {date(2024, 2, 28), date(2024, 2, 29), date(2024, 3, 1)}
    assert calculate_streak(date(2024, 3, 1), schedules, leap_completions) == 3

    year_schedule = [ScheduleWindow(ALL_DAYS, date(2025, 12, 31))]
    year_completions = {date(2025, 12, 31), date(2026, 1, 1)}
    assert calculate_streak(date(2026, 1, 1), year_schedule, year_completions) == 2
