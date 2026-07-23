"""Rolling ranking engine + snapshot writer."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.config import get_settings
from backend.db import db_session, get_meta, set_meta
from backend.media_config import load_media_roster
from backend.themes.radar import build_radar_profiles

log = logging.getLogger("desinfo.scoring")

WINDOW_DAYS = {"7d": 7, "30d": 30, "90d": 90, "365d": 365}


def parse_window(window_key: str) -> int:
    key = window_key.strip().lower()
    if key not in WINDOW_DAYS:
        raise ValueError(f"Invalid window '{window_key}', expected one of {list(WINDOW_DAYS)}")
    return WINDOW_DAYS[key]


def _ms_since(days: int, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    return int(start.timestamp() * 1000)


def compute_ranking(window_key: str | None = None, *, now: datetime | None = None) -> dict[str, Any]:
    settings = get_settings()
    window_key = (window_key or settings.default_window).strip().lower()
    days = parse_window(window_key)
    now = now or datetime.now(timezone.utc)
    since_ms = _ms_since(days, now)

    roster = load_media_roster()
    roster_media = roster.get("media") or []
    roster_ids = [m["id"] for m in roster_media if m.get("id")]
    roster_by_id = {m["id"]: m for m in roster_media if m.get("id")}

    # Fallback: if roster empty, use all media present in DB with any attribution
    with db_session() as conn:
        if not roster_ids:
            rows = conn.execute(
                "SELECT DISTINCT media_id FROM note_media"
            ).fetchall()
            roster_ids = [r["media_id"] for r in rows]

        media_meta: dict[str, dict] = {}
        if roster_ids:
            placeholders = ",".join("?" * len(roster_ids))
            rows = conn.execute(
                f"SELECT id, name, domains, x_handle FROM media WHERE id IN ({placeholders})",
                roster_ids,
            ).fetchall()
            for row in rows:
                media_meta[row["id"]] = dict(row)
        for mid in roster_ids:
            if mid in media_meta:
                continue
            m = roster_by_id.get(mid)
            if m:
                media_meta[mid] = {
                    "id": mid,
                    "name": m.get("name", mid),
                    "domains": ",".join(m.get("domains") or []),
                    "x_handle": m.get("x_handle"),
                }

        counts: dict[str, int] = {mid: 0 for mid in roster_ids}
        if roster_ids:
            placeholders = ",".join("?" * len(roster_ids))
            q = f"""
                SELECT nm.media_id, COUNT(DISTINCT nm.note_id) AS cn
                FROM note_media nm
                JOIN notes n ON n.note_id = nm.note_id
                WHERE n.is_helpful=1 AND n.created_at_ms >= ?
                  AND nm.media_id IN ({placeholders})
                GROUP BY nm.media_id
            """
            rows = conn.execute(q, [since_ms, *roster_ids]).fetchall()
            for r in rows:
                counts[r["media_id"]] = int(r["cn"])

        post_counts: dict[str, int | None] = {mid: None for mid in roster_ids}
        any_posts = False
        if roster_ids:
            placeholders = ",".join("?" * len(roster_ids))
            rows = conn.execute(
                f"""
                SELECT media_id, post_count
                FROM media_post_windows
                WHERE window_key=? AND media_id IN ({placeholders})
                """,
                [window_key, *roster_ids],
            ).fetchall()
            for r in rows:
                pc = int(r["post_count"])
                post_counts[r["media_id"]] = pc
                if pc > 0:
                    any_posts = True

        last_ingest = get_meta(conn, "last_ingest_at")
        radar_by_media = build_radar_profiles(
            conn, media_ids=roster_ids, window_key=window_key, now=now
        )

    metric_mode = "post_cn" if any_posts else "cn_only"

    entries: list[dict[str, Any]] = []
    for mid in roster_ids:
        meta = media_meta.get(mid) or {"id": mid, "name": mid, "domains": "", "x_handle": None}
        cn = counts.get(mid, 0)
        posts = post_counts.get(mid)
        rate = None
        ratio_post_cn = None
        if posts is not None and posts > 0:
            rate = cn / posts
            ratio_post_cn = posts / cn if cn > 0 else None
        else:
            # 0 posts = pas de ratio fiable (compte muet / sync incomplet)
            if posts == 0:
                posts = None
            rate = None
            ratio_post_cn = None

        entries.append(
            {
                "media_id": mid,
                "name": meta.get("name") or mid,
                "domains": (meta.get("domains") or "").split(",") if isinstance(meta.get("domains"), str) else meta.get("domains") or [],
                "x_handle": meta.get("x_handle"),
                "cn_count": cn,
                "post_count": posts,
                "rate_cn_per_post": rate,
                "ratio_post_per_cn": ratio_post_cn,
                "radar": radar_by_media.get(mid),
            }
        )

    if metric_mode == "post_cn":
        entries.sort(
            key=lambda e: (
                e["rate_cn_per_post"] is None,
                -(e["rate_cn_per_post"] or 0),
                -e["cn_count"],
                e["name"],
            )
        )
    else:
        entries.sort(key=lambda e: (-e["cn_count"], e["name"]))

    for i, e in enumerate(entries, start=1):
        e["rank"] = i
        e["delta_rank"] = None  # filled vs previous snapshot if available

    prev_ranks = _load_previous_ranks(window_key)
    for e in entries:
        prev = prev_ranks.get(e["media_id"])
        if prev is not None:
            e["delta_rank"] = prev - e["rank"]

    snapshot = {
        "generated_at": now.isoformat(),
        "window": window_key,
        "window_days": days,
        "metric_mode": metric_mode,
        "last_ingest_at": last_ingest,
        "roster_size": len(roster_ids),
        "items": entries,
    }
    return snapshot


def _load_previous_ranks(window_key: str) -> dict[str, int]:
    settings = get_settings()
    path = settings.snapshots_dir / f"latest_{window_key}.json"
    if not path.exists():
        # also try unified latest
        path = settings.snapshots_dir / "latest.json"
        if not path.exists():
            return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("window") != window_key and path.name == "latest.json":
            return {}
        return {it["media_id"]: it["rank"] for it in data.get("items") or [] if "media_id" in it}
    except (json.JSONDecodeError, OSError, KeyError, TypeError):
        return {}


def write_snapshot(snapshot: dict[str, Any]) -> Path:
    settings = get_settings()
    settings.snapshots_dir.mkdir(parents=True, exist_ok=True)
    window_key = snapshot["window"]
    latest_w = settings.snapshots_dir / f"latest_{window_key}.json"
    latest = settings.snapshots_dir / "latest.json"

    payload = json.dumps(snapshot, ensure_ascii=False, indent=2)
    tmp = latest_w.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(latest_w)

    # Default window also updates latest.json
    if window_key == settings.default_window:
        tmp = latest.with_suffix(".json.tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(latest)

    with db_session() as conn:
        conn.execute(
            "INSERT INTO ranking_snapshots(window_key, created_at, metric_mode, path) VALUES (?,?,?,?)",
            (window_key, snapshot["generated_at"], snapshot["metric_mode"], str(latest_w)),
        )
        set_meta(conn, f"last_snapshot_{window_key}", snapshot["generated_at"])

    log.info("wrote snapshot %s mode=%s items=%s", window_key, snapshot["metric_mode"], len(snapshot["items"]))
    return latest_w


def score_all_windows(windows: list[str] | None = None) -> list[Path]:
    settings = get_settings()
    windows = windows or list(WINDOW_DAYS.keys())
    paths = []
    for w in windows:
        snap = compute_ranking(w)
        paths.append(write_snapshot(snap))
    # Ensure default latest
    if settings.default_window not in windows:
        snap = compute_ranking(settings.default_window)
        paths.append(write_snapshot(snap))
    return paths
