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


def _media_attribution_stats(
    conn,
    *,
    media_ids: list[str],
    since_ms: int,
) -> dict[str, dict[str, int]]:
    """Per media: attributed, classified, unclassified counts in window."""
    out = {mid: {"attributed": 0, "classified": 0, "unclassified": 0} for mid in media_ids}
    if not media_ids:
        return out
    placeholders = ",".join("?" * len(media_ids))
    rows = conn.execute(
        f"""
        SELECT
          nm.media_id,
          COUNT(DISTINCT nm.note_id) AS attributed,
          COUNT(DISTINCT CASE WHEN nt.note_id IS NOT NULL THEN nm.note_id END) AS classified
        FROM note_media nm
        JOIN notes n ON n.note_id = nm.note_id
        LEFT JOIN note_theme nt ON nt.note_id = nm.note_id
        WHERE n.is_helpful = 1
          AND n.created_at_ms >= ?
          AND nm.media_id IN ({placeholders})
        GROUP BY nm.media_id
        """,
        [since_ms, *media_ids],
    ).fetchall()
    for r in rows:
        mid = r["media_id"]
        if mid not in out:
            continue
        attributed = int(r["attributed"] or 0)
        classified = int(r["classified"] or 0)
        out[mid] = {
            "attributed": attributed,
            "classified": classified,
            "unclassified": max(0, attributed - classified),
        }
    return out


def _politician_attribution_stats(
    conn,
    *,
    politician_ids: list[str],
    since_ms: int,
) -> dict[str, dict[str, int]]:
    out = {
        pid: {"attributed": 0, "classified": 0, "unclassified": 0} for pid in politician_ids
    }
    if not politician_ids:
        return out
    placeholders = ",".join("?" * len(politician_ids))
    rows = conn.execute(
        f"""
        SELECT
          np.politician_id,
          COUNT(DISTINCT np.note_id) AS attributed,
          COUNT(DISTINCT CASE WHEN nt.note_id IS NOT NULL THEN np.note_id END) AS classified
        FROM note_politician np
        JOIN notes n ON n.note_id = np.note_id
        LEFT JOIN note_theme nt ON nt.note_id = np.note_id
        WHERE n.is_helpful = 1
          AND n.created_at_ms >= ?
          AND np.politician_id IN ({placeholders})
        GROUP BY np.politician_id
        """,
        [since_ms, *politician_ids],
    ).fetchall()
    for r in rows:
        pid = r["politician_id"]
        if pid not in out:
            continue
        attributed = int(r["attributed"] or 0)
        classified = int(r["classified"] or 0)
        out[pid] = {
            "attributed": attributed,
            "classified": classified,
            "unclassified": max(0, attributed - classified),
        }
    return out


def compute_media_theme_counts(
    conn,
    *,
    media_ids: list[str],
    since_ms: int,
) -> tuple[dict[str, dict[str, int]], dict[str, int]]:
    """Return ({media_id: {theme: cn_count}}, {media_id: autre_count})."""
    counts: dict[str, dict[str, int]] = {
        mid: {t: 0 for t in RADAR_THEMES} for mid in media_ids
    }
    autre: dict[str, int] = {mid: 0 for mid in media_ids}
    if not media_ids:
        return counts, autre
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
        GROUP BY nm.media_id, nt.theme
        """,
        [since_ms, *media_ids],
    ).fetchall()
    for r in rows:
        mid = r["media_id"]
        theme = r["theme"]
        cn = int(r["cn"])
        if mid not in counts:
            continue
        if theme == "autre":
            autre[mid] = cn
        elif theme in counts[mid]:
            counts[mid][theme] = cn
    return counts, autre


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
    theme_counts, autre_counts = compute_media_theme_counts(
        conn, media_ids=media_ids, since_ms=since_ms
    )
    stats = _media_attribution_stats(conn, media_ids=media_ids, since_ms=since_ms)

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
        st = stats.get(mid) or {"attributed": 0, "classified": 0, "unclassified": 0}
        attributed = st["attributed"]
        classified = st["classified"]
        coverage = classified / attributed if attributed > 0 else 0.0
        profiles[mid] = {
            "axes": axes,
            "autre_count": autre_counts.get(mid, 0),
            "unclassified_count": st["unclassified"],
            "attributed_count": attributed,
            "direction": "outer_more_cn_within_media",
            "coverage": round(coverage, 3),
        }
    return profiles


def compute_politician_theme_counts(
    conn,
    *,
    politician_ids: list[str],
    since_ms: int,
) -> tuple[dict[str, dict[str, int]], dict[str, int]]:
    """Return ({politician_id: {theme: cn_count}}, {politician_id: autre_count})."""
    counts: dict[str, dict[str, int]] = {
        pid: {t: 0 for t in RADAR_THEMES} for pid in politician_ids
    }
    autre: dict[str, int] = {pid: 0 for pid in politician_ids}
    if not politician_ids:
        return counts, autre
    placeholders = ",".join("?" * len(politician_ids))
    rows = conn.execute(
        f"""
        SELECT np.politician_id, nt.theme, COUNT(DISTINCT np.note_id) AS cn
        FROM note_politician np
        JOIN notes n ON n.note_id = np.note_id
        JOIN note_theme nt ON nt.note_id = np.note_id
        WHERE n.is_helpful = 1
          AND n.created_at_ms >= ?
          AND np.politician_id IN ({placeholders})
        GROUP BY np.politician_id, nt.theme
        """,
        [since_ms, *politician_ids],
    ).fetchall()
    for r in rows:
        pid = r["politician_id"]
        theme = r["theme"]
        cn = int(r["cn"])
        if pid not in counts:
            continue
        if theme == "autre":
            autre[pid] = cn
        elif theme in counts[pid]:
            counts[pid][theme] = cn
    return counts, autre


def build_politician_radar_profiles(
    conn,
    *,
    politician_ids: list[str],
    window_key: str,
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Per-candidate radar: cn_count + weight (100 = thème le plus fort du candidat)."""
    now = now or datetime.now(timezone.utc)
    days = _parse_window(window_key)
    since_ms = _ms_since(days, now)
    theme_counts, autre_counts = compute_politician_theme_counts(
        conn, politician_ids=politician_ids, since_ms=since_ms
    )
    stats = _politician_attribution_stats(
        conn, politician_ids=politician_ids, since_ms=since_ms
    )

    profiles: dict[str, dict[str, Any]] = {}
    for pid in politician_ids:
        counts = theme_counts[pid]
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
        st = stats.get(pid) or {"attributed": 0, "classified": 0, "unclassified": 0}
        attributed = st["attributed"]
        classified = st["classified"]
        coverage = classified / attributed if attributed > 0 else 0.0
        profiles[pid] = {
            "axes": axes,
            "autre_count": autre_counts.get(pid, 0),
            "unclassified_count": st["unclassified"],
            "attributed_count": attributed,
            "direction": "outer_more_cn_within_entity",
            "coverage": round(coverage, 3),
        }
    return profiles
