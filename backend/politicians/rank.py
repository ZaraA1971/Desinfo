"""Rolling ranking engine + snapshot writer — politicians.

Mirrors backend/scoring/rank.py (compute_ranking / write_snapshot / score_all_*)
but sources note<->politician links (note_politician) and X post windows
(politician_post_windows) instead of the media tables. WINDOW_DAYS is reused
from backend.windows.time via scoring.rank — a single formula/window definition per cursor.md.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.config import get_settings
from backend.db import db_session, get_meta, set_meta
from backend.politicians.config import load_politicians_roster
from backend.scoring.rank import WINDOW_DAYS, cn_window_bounds, parse_window, window_as_of
from backend.themes.radar import build_politician_radar_profiles

log = logging.getLogger("desinfo.politicians.scoring")


def compute_ranking(window_key: str | None = None, *, now: datetime | None = None) -> dict[str, Any]:
    settings = get_settings()
    window_key = (window_key or settings.default_window).strip().lower()
    days = parse_window(window_key)
    generated_at = now or datetime.now(timezone.utc)
    as_of = window_as_of(window_key, generated_at)
    since_ms, until_ms = cn_window_bounds(days, as_of)
    radar_as_of = datetime.fromtimestamp(until_ms / 1000, tz=timezone.utc)

    roster = load_politicians_roster()
    candidates = roster.get("candidates") or []
    roster_ids = [c["id"] for c in candidates if c.get("id")]
    roster_by_id = {c["id"]: c for c in candidates if c.get("id")}

    with db_session() as conn:
        if not roster_ids:
            rows = conn.execute(
                "SELECT DISTINCT politician_id FROM note_politician"
            ).fetchall()
            roster_ids = [r["politician_id"] for r in rows]

        politician_meta: dict[str, dict] = {}
        if roster_ids:
            placeholders = ",".join("?" * len(roster_ids))
            rows = conn.execute(
                f"SELECT id, name, party, x_handle FROM politicians WHERE id IN ({placeholders})",
                roster_ids,
            ).fetchall()
            for row in rows:
                politician_meta[row["id"]] = dict(row)
        for pid in roster_ids:
            if pid in politician_meta:
                continue
            c = roster_by_id.get(pid)
            if c:
                politician_meta[pid] = {
                    "id": pid,
                    "name": c.get("name", pid),
                    "party": c.get("party"),
                    "x_handle": c.get("x_handle"),
                }

        counts: dict[str, int] = {pid: 0 for pid in roster_ids}
        if roster_ids:
            placeholders = ",".join("?" * len(roster_ids))
            q = f"""
                SELECT np.politician_id, COUNT(DISTINCT np.note_id) AS cn
                FROM note_politician np
                JOIN notes n ON n.note_id = np.note_id
                WHERE n.is_helpful=1
                  AND n.created_at_ms >= ? AND n.created_at_ms < ?
                  AND np.politician_id IN ({placeholders})
                GROUP BY np.politician_id
            """
            rows = conn.execute(q, [since_ms, until_ms, *roster_ids]).fetchall()
            for r in rows:
                counts[r["politician_id"]] = int(r["cn"])

        post_counts: dict[str, int | None] = {pid: None for pid in roster_ids}
        any_posts = False
        if roster_ids:
            placeholders = ",".join("?" * len(roster_ids))
            rows = conn.execute(
                f"""
                SELECT politician_id, post_count
                FROM politician_post_windows
                WHERE window_key=? AND politician_id IN ({placeholders})
                """,
                [window_key, *roster_ids],
            ).fetchall()
            for r in rows:
                pc = int(r["post_count"])
                post_counts[r["politician_id"]] = pc
                if pc > 0:
                    any_posts = True

        last_ingest = get_meta(conn, "last_ingest_at")
        radar_by_politician = build_politician_radar_profiles(
            conn, politician_ids=roster_ids, window_key=window_key, now=radar_as_of
        )

    metric_mode = "post_cn" if any_posts else "cn_only"

    entries: list[dict[str, Any]] = []
    for pid in roster_ids:
        meta = politician_meta.get(pid) or {"id": pid, "name": pid, "party": None, "x_handle": None}
        cn = counts.get(pid, 0)
        posts = post_counts.get(pid)
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
                "politician_id": pid,
                "name": meta.get("name") or pid,
                "party": meta.get("party"),
                "x_handle": meta.get("x_handle"),
                "cn_count": cn,
                "post_count": posts,
                "rate_cn_per_post": rate,
                "ratio_post_per_cn": ratio_post_cn,
                "radar": radar_by_politician.get(pid),
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
        prev = prev_ranks.get(e["politician_id"])
        if prev is not None:
            e["delta_rank"] = prev - e["rank"]

    snapshot = {
        "kind": "politicians",
        "generated_at": generated_at.isoformat(),
        "window": window_key,
        "window_days": days,
        "cn_as_of": as_of.isoformat(),
        "metric_mode": metric_mode,
        "last_ingest_at": last_ingest,
        "roster_size": len(roster_ids),
        "items": entries,
    }
    return snapshot


def _load_previous_ranks(window_key: str) -> dict[str, int]:
    settings = get_settings()
    path = settings.snapshots_dir / f"latest_politicians_{window_key}.json"
    if not path.exists():
        # also try unified politicians latest
        path = settings.snapshots_dir / "latest_politicians.json"
        if not path.exists():
            return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("window") != window_key and path.name == "latest_politicians.json":
            return {}
        return {
            it["politician_id"]: it["rank"]
            for it in data.get("items") or []
            if "politician_id" in it
        }
    except (json.JSONDecodeError, OSError, KeyError, TypeError):
        return {}


def write_snapshot(snapshot: dict[str, Any]) -> Path:
    settings = get_settings()
    settings.snapshots_dir.mkdir(parents=True, exist_ok=True)
    window_key = snapshot["window"]
    latest_w = settings.snapshots_dir / f"latest_politicians_{window_key}.json"
    latest = settings.snapshots_dir / "latest_politicians.json"

    payload = json.dumps(snapshot, ensure_ascii=False, indent=2)
    tmp = latest_w.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(latest_w)

    # Default window also updates the unified politicians "latest" file
    if window_key == settings.default_window:
        tmp = latest.with_suffix(".json.tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(latest)

    with db_session() as conn:
        conn.execute(
            "INSERT INTO ranking_snapshots(window_key, created_at, metric_mode, path) VALUES (?,?,?,?)",
            (
                f"politicians_{window_key}",
                snapshot["generated_at"],
                snapshot["metric_mode"],
                str(latest_w),
            ),
        )
        set_meta(conn, f"last_snapshot_politicians_{window_key}", snapshot["generated_at"])

    log.info(
        "wrote politicians snapshot %s mode=%s items=%s",
        window_key,
        snapshot["metric_mode"],
        len(snapshot["items"]),
    )
    return latest_w


def score_all_politicians_windows(windows: list[str] | None = None) -> list[Path]:
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
