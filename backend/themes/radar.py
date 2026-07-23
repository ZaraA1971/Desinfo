"""Radar profile: thematic CN weights per media (branch ∝ CN count)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from backend.themes.taxonomy import RADAR_THEMES, THEME_LABELS_FR

_WINDOW_DAYS = {"7d": 7, "30d": 30, "90d": 90, "365d": 365}


def _parse_window(window_key: str) -> int:
    key = window_key.strip().lower()
    if key not in _WINDOW_DAYS:
        raise ValueError(f"Invalid window '{window_key}'")
    return _WINDOW_DAYS[key]


def _ms_since(days: int, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    return int(start.timestamp() * 1000)


def compute_media_theme_counts(
    conn,
    *,
    media_ids: list[str],
    since_ms: int,
) -> dict[str, dict[str, int]]:
    """Return {media_id: {theme: cn_count}} for radar themes only."""
    counts: dict[str, dict[str, int]] = {
        mid: {t: 0 for t in RADAR_THEMES} for mid in media_ids
    }
    if not media_ids:
        return counts
    placeholders = ",".join("?" * len(media_ids))
    rows = conn.execute(
        f"""
        SELECT nm.media_id, nt.theme, COUNT(DISTINCT nm.note_id) AS cn
        FROM note_media nm
        JOIN notes n ON n.note_id = nm.note_id
        JOIN note_theme nt ON nt.note_id = nm.note_id
        WHERE n.is_helpful = 1
          AND n.created_at_ms >= ?
          AND nm.media_id IN ({placeholders})
          AND nt.theme != 'autre'
        GROUP BY nm.media_id, nt.theme
        """,
        [since_ms, *media_ids],
    ).fetchall()
    for r in rows:
        mid = r["media_id"]
        theme = r["theme"]
        if mid in counts and theme in counts[mid]:
            counts[mid][theme] = int(r["cn"])
    return counts


def build_radar_profiles(
    conn,
    *,
    media_ids: list[str],
    window_key: str,
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Per-media radar: cn_count + weight (100 = thème le plus fort du média)."""
    now = now or datetime.now(timezone.utc)
    days = _parse_window(window_key)
    since_ms = _ms_since(days, now)
    theme_counts = compute_media_theme_counts(
        conn, media_ids=media_ids, since_ms=since_ms
    )

    coverage = 0.0
    if media_ids:
        placeholders = ",".join("?" * len(media_ids))
        row = conn.execute(
            f"""
            SELECT
              COUNT(DISTINCT nm.note_id) AS attributed,
              COUNT(DISTINCT CASE WHEN nt.note_id IS NOT NULL THEN nm.note_id END) AS classified
            FROM note_media nm
            JOIN notes n ON n.note_id = nm.note_id
            LEFT JOIN note_theme nt ON nt.note_id = nm.note_id
            WHERE n.is_helpful = 1
              AND n.created_at_ms >= ?
              AND nm.media_id IN ({placeholders})
            """,
            [since_ms, *media_ids],
        ).fetchone()
        attributed = int(row["attributed"] or 0)
        classified = int(row["classified"] or 0)
        coverage = classified / attributed if attributed > 0 else 0.0

    profiles: dict[str, dict[str, Any]] = {}
    for mid in media_ids:
        counts = theme_counts[mid]
        max_cn = max(counts.values()) if counts else 0
        axes = []
        for t in RADAR_THEMES:
            cn = counts[t]
            weight = round(100.0 * cn / max_cn, 1) if max_cn > 0 and cn > 0 else 0.0
            axes.append(
                {
                    "theme": t,
                    "label": THEME_LABELS_FR.get(t, t),
                    "cn_count": cn,
                    "weight": weight,
                }
            )
        profiles[mid] = {
            "axes": axes,
            "direction": "outer_more_cn_within_media",
            "coverage": round(coverage, 3),
        }
    return profiles
