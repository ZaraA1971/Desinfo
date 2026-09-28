"""Window availability — cascade fills 30/90/365 week by week (no X API)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.db import db_session
from backend.windows.time import WINDOW_DAYS, last_weekly_as_of
from backend.windows.coverage import (
    coverage_need,
    kind_tables,
    min_days_for,
    roster_entity_ids,
    window_available,
    window_day_range,
)


def compute_windows_status(*, kind: str = "media", now: datetime | None = None) -> dict[str, dict[str, Any]]:
    """
    Per window:
    - available: 7d always; longer windows only when coverage is met
    - metric_mode: post_cn | cn_only when available
    - progress: share of roster filled (0–1)
    """
    need = coverage_need()
    now = now or last_weekly_as_of()
    roster_ids = roster_entity_ids(kind)
    roster_size = len(roster_ids)
    if roster_size <= 0:
        return {w: {"available": w == "7d", "metric_mode": "cn_only", "progress": 0.0} for w in WINDOW_DAYS}

    tables = kind_tables(kind)
    daily_table = tables["daily"]
    windows_table = tables["windows"]
    id_col = tables["id_col"]
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
            start_day, end_day = window_day_range(days, now)
            min_days = min_days_for(days, need)

            ready_count = 0
            for entity_id in roster_ids:
                row = conn.execute(
                    f"""
                    SELECT COUNT(*) AS n
                    FROM {daily_table}
                    WHERE {id_col}=? AND day>=? AND day<?
                    """,
                    (entity_id, start_day, end_day),
                ).fetchone()
                if int(row["n"] or 0) >= min_days:
                    ready_count += 1

            placeholders = ",".join("?" * len(roster_ids))
            n_written = int(
                conn.execute(
                    f"""
                    SELECT COUNT(*) AS n FROM {windows_table}
                    WHERE window_key=? AND {id_col} IN ({placeholders})
                    """,
                    [w, *roster_ids],
                ).fetchone()["n"]
            )
            available = window_available(
                daily_ready=ready_count,
                written=n_written,
                roster_size=roster_size,
                need=need,
            )
            progress = max(ready_count, n_written) / roster_size

            metric_mode = None
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
                "metric_mode": metric_mode,
                "progress": round(progress, 3),
                "min_days": min_days,
                "ready_entities": ready_count,
                "written_entities": n_written,
                "roster_size": roster_size,
            }

    return out
