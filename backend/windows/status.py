"""Window availability — cascade fills 30/90/365 week by week (no X API)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from backend.config import get_settings
from backend.db import db_session
from backend.media_config import load_media_roster
from backend.politicians.config import load_politicians_roster
from backend.scoring.rank import WINDOW_DAYS


def _roster_size(kind: str) -> int:
    if kind == "politicians":
        return len(load_politicians_roster().get("candidates") or [])
    return len(load_media_roster().get("media") or [])


def compute_windows_status(*, kind: str = "media", now: datetime | None = None) -> dict[str, dict[str, Any]]:
    """
    Per window:
    - available: clickable in UI (7d always; longer windows when cascade quota met)
    - metric_mode: post_cn | cn_only when available
    - progress: share of roster with enough daily buckets (0–1)
    """
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    coverage_need = max(0.1, min(1.0, settings.cascade_coverage))
    roster_size = _roster_size(kind)
    if roster_size <= 0:
        return {w: {"available": w == "7d", "metric_mode": "cn_only", "progress": 0.0} for w in WINDOW_DAYS}

    if kind == "politicians":
        daily_table = "politician_posts_daily"
        windows_table = "politician_post_windows"
        id_col = "politician_id"
        roster_ids = [
            c["id"] for c in load_politicians_roster().get("candidates") or [] if c.get("id")
        ]
    else:
        daily_table = "media_posts_daily"
        windows_table = "media_post_windows"
        id_col = "media_id"
        roster_ids = [
            m["id"] for m in load_media_roster().get("media") or [] if m.get("id")
        ]

    out: dict[str, dict[str, Any]] = {}

    with db_session() as conn:
        for w in WINDOW_DAYS:
            if w == "7d":
                n_posts = int(
                    conn.execute(
                        f"""
                        SELECT COUNT(*) AS n FROM {windows_table}
                        WHERE window_key='7d' AND post_count > 0
                        """
                    ).fetchone()["n"]
                )
                out[w] = {
                    "available": True,
                    "metric_mode": "post_cn" if n_posts > 0 else "cn_only",
                    "progress": 1.0,
                }
                continue

            days = WINDOW_DAYS[w]
            start_day = (now - timedelta(days=days)).strftime("%Y-%m-%d")
            end_day = now.strftime("%Y-%m-%d")
            min_days = max(1, int(days * coverage_need))

            ready_count = 0
            for entity_id in roster_ids:
                row = conn.execute(
                    f"""
                    SELECT COUNT(*) AS n
                    FROM {daily_table}
                    WHERE {id_col}=? AND day>=? AND day<=?
                    """,
                    (entity_id, start_day, end_day),
                ).fetchone()
                if int(row["n"] or 0) >= min_days:
                    ready_count += 1

            progress = ready_count / roster_size if roster_size else 0.0
            available = progress >= coverage_need

            metric_mode = "cn_only"
            if available:
                n_posts = int(
                    conn.execute(
                        f"""
                        SELECT COUNT(*) AS n FROM {windows_table}
                        WHERE window_key=? AND post_count > 0
                        """,
                        (w,),
                    ).fetchone()["n"]
                )
                metric_mode = "post_cn" if n_posts > 0 else "cn_only"

            out[w] = {
                "available": available,
                "metric_mode": metric_mode if available else None,
                "progress": round(progress, 3),
                "min_days": min_days,
                "ready_entities": ready_count,
                "roster_size": roster_size,
            }

    return out
