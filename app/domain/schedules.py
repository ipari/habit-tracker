from dataclasses import dataclass
from datetime import date

WEEKDAY_LABELS = ("월", "화", "수", "목", "금", "토", "일")


@dataclass(frozen=True)
class ScheduleWindow:
    weekdays_mask: int
    effective_from: date
    effective_until: date | None = None


def weekdays_to_mask(weekdays: list[int] | tuple[int, ...]) -> int:
    if not weekdays or any(day < 0 or day > 6 for day in weekdays):
        raise ValueError("Select at least one valid weekday")
    return sum(1 << day for day in set(weekdays))


def mask_to_weekdays(mask: int) -> tuple[int, ...]:
    if mask < 1 or mask > 127:
        raise ValueError("Invalid weekday mask")
    return tuple(day for day in range(7) if mask & (1 << day))


def schedule_for_date(schedules: list[ScheduleWindow], local_date: date) -> ScheduleWindow | None:
    matches = [
        schedule
        for schedule in schedules
        if schedule.effective_from <= local_date
        and (schedule.effective_until is None or local_date < schedule.effective_until)
    ]
    if len(matches) > 1:
        raise ValueError("Overlapping habit schedules")
    return matches[0] if matches else None


def is_scheduled(schedule: ScheduleWindow | None, local_date: date) -> bool:
    return schedule is not None and bool(schedule.weekdays_mask & (1 << local_date.weekday()))
