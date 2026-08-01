from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def scheduled_utc(local_date: date, local_time: time, timezone: str) -> datetime:
    zone = ZoneInfo(timezone)
    naive = datetime.combine(local_date, local_time)
    candidate = naive.replace(tzinfo=zone, fold=0).astimezone(UTC)
    normalized = candidate.astimezone(zone)
    if normalized.replace(tzinfo=None) != naive:
        return normalized.astimezone(UTC)
    return candidate


def scheduled_occurrences(
    *,
    weekdays_mask: int,
    local_time: time,
    timezone: str,
    window_start: datetime,
    window_end: datetime,
) -> list[datetime]:
    if window_start.tzinfo is None or window_end.tzinfo is None:
        raise ValueError("Scheduling window must be timezone-aware")
    if window_end < window_start:
        raise ValueError("Scheduling window is reversed")
    zone = ZoneInfo(timezone)
    first_date = (window_start.astimezone(zone) - timedelta(days=1)).date()
    last_date = window_end.astimezone(zone).date()
    occurrences: list[datetime] = []
    local_date = first_date
    while local_date <= last_date:
        if weekdays_mask & (1 << local_date.weekday()):
            occurrence = scheduled_utc(local_date, local_time, timezone)
            if window_start < occurrence <= window_end:
                occurrences.append(occurrence)
        local_date += timedelta(days=1)
    return occurrences
