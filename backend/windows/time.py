"""One harvest cut, one clock. Used by score, cascade, skip, and radar."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.config import get_settings

WINDOW_DAYS = {"7d": 7, "30d": 30, "90d": 90, "365d": 365}


def parse_window(window_key: str) -> int:
    key = window_key.strip().lower()
    if key not in WINDOW_DAYS:
        raise ValueError(f"Invalid window '{window_key}', expected one of {list(WINDOW_DAYS)}")
    return WINDOW_DAYS[key]


def as_utc(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def harvest_monday_utc(now: datetime | None = None) -> datetime:
    """Monday 06:00 UTC on or before now — same instant every week."""
    settings = get_settings()
    now = as_utc(now)
    hour = max(0, min(23, int(settings.harvest_hour_utc)))
    cut = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    cut -= timedelta(days=now.weekday())
    if cut > now:
        cut -= timedelta(days=7)
    return cut


def last_weekly_as_of(now: datetime | None = None) -> datetime:
    """Alias — this week's harvest cut, not the job start time."""
    return harvest_monday_utc(now)


def window_ms_bounds(days: int, as_of: datetime) -> tuple[int, int]:
    """Half-open window [as_of - days, as_of)."""
    as_of = as_utc(as_of)
    until_ms = int(as_of.timestamp() * 1000)
    since_ms = int((as_of - timedelta(days=days)).timestamp() * 1000)
    return since_ms, until_ms
