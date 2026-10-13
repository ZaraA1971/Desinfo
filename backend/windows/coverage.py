"""Shared harvest-week math for cascade, X skip, and window availability.

One cut (Monday 06:00 UTC). One day range. One coverage threshold.
Skip X only if this week's daily buckets are already there — never a 168h clock.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from backend.config import get_settings
from backend.media_config import load_media_roster
from backend.politicians.config import load_politicians_roster
from backend.windows.time import WINDOW_DAYS, last_weekly_as_of


def coverage_need() -> float:
    settings = get_settings()
    return max(0.1, min(1.0, settings.cascade_coverage))


def min_days_for(days: int, need: float | None = None) -> int:
    return max(1, int(days * (coverage_need() if need is None else need)))


def window_day_range(days: int, as_of: datetime) -> tuple[str, str]:
    """Half-open calendar range [as_of - days, as_of) as YYYY-MM-DD."""
    start = (as_of - timedelta(days=days)).strftime("%Y-%m-%d")
    end = as_of.strftime("%Y-%m-%d")
    return start, end


def harvest_week_range(as_of: datetime | None = None) -> tuple[str, str]:
    """The Monday–Monday week that just ended."""
    return window_day_range(7, as_of or last_weekly_as_of())


def cascade_targets() -> list[str]:
    settings = get_settings()
    return [w for w in settings.cascade_windows if w in WINDOW_DAYS and w != "7d"]


def force_x_refresh() -> bool:
    return get_settings().x_sync_min_age_hours <= 0


def complete_daily_buckets(
    buckets: list[tuple[str, int]],
    since: datetime,
    until: datetime,
) -> list[tuple[str, int]]:
    """Every calendar day in [since, until), 0 if X omitted the day."""
    by_day = {day: int(count) for day, count in buckets if day}
    out: list[tuple[str, int]] = []
    day = since.date()
    end = until.date()
    while day < end:
        key = day.isoformat()
        out.append((key, by_day.get(key, 0)))
        day += timedelta(days=1)
    return out


def window_available(*, daily_ready: int, written: int, roster_size: int, need: float | None = None) -> bool:
    """Open only when enough of the roster is filled. Not enough → stay closed."""
    if roster_size <= 0:
        return False
    threshold = coverage_need() if need is None else need
    return (daily_ready / roster_size) >= threshold or (written / roster_size) >= threshold


def roster_entity_ids(kind: str) -> list[str]:
    if kind == "politicians":
        return [c["id"] for c in load_politicians_roster().get("candidates") or [] if c.get("id")]
    return [m["id"] for m in load_media_roster().get("media") or [] if m.get("id")]


def kind_tables(kind: str) -> dict[str, str]:
    if kind == "politicians":
        return {
            "daily": "politician_posts_daily",
            "windows": "politician_post_windows",
            "id_col": "politician_id",
            "meta_cascade": "last_cascade_politicians_at",
        }
    return {
        "daily": "media_posts_daily",
        "windows": "media_post_windows",
        "id_col": "media_id",
        "meta_cascade": "last_cascade_at",
    }
