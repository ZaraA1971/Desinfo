"""Bootstrap starter set from 365d CN attribution."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from backend.config import get_settings
from backend.db import db_session
from backend.media_config import load_media_domains, save_media_roster
from backend.scoring.rank import _ms_since

log = logging.getLogger("desinfo.bootstrap")


def bootstrap_roster(days: int | None = None, min_cn: int | None = None) -> dict[str, Any]:
    settings = get_settings()
    days = days if days is not None else settings.bootstrap_days
    min_cn = min_cn if min_cn is not None else settings.roster_min_cn
    since_ms = _ms_since(days)

    domains_cfg = {m["id"]: m for m in load_media_domains()}

    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT nm.media_id AS media_id, COUNT(DISTINCT nm.note_id) AS cn
            FROM note_media nm
            JOIN notes n ON n.note_id = nm.note_id
            WHERE n.is_helpful=1 AND n.created_at_ms >= ?
            GROUP BY nm.media_id
            HAVING cn >= ?
            ORDER BY cn DESC, media_id ASC
            """,
            (since_ms, min_cn),
        ).fetchall()

    media_out: list[dict[str, Any]] = []
    for i, row in enumerate(rows, start=1):
        mid = row["media_id"]
        base = domains_cfg.get(mid, {"id": mid, "name": mid, "domains": [], "x_handle": None})
        media_out.append(
            {
                "id": mid,
                "name": base.get("name", mid),
                "domains": base.get("domains") or [],
                "x_handle": base.get("x_handle"),
                "rank_bootstrap": i,
                "cn_365d": int(row["cn"]) if days == 365 else int(row["cn"]),
                f"cn_{days}d": int(row["cn"]),
            }
        )

    roster = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": days,
        "min_cn": min_cn,
        "media": media_out,
    }
    save_media_roster(roster)
    log.info("bootstrap roster: %s media (min_cn=%s, days=%s)", len(media_out), min_cn, days)
    return roster
