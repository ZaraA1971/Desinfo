"""One X path: 7d counts/recent per @handle, then cascade 30/90/365 from daily."""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from backend.config import get_settings
from backend.db import db_session, set_meta
from backend.media_config import iter_x_handles, load_media_roster
from backend.politicians.config import load_politicians_roster
from backend.windows.coverage import (
    cascade_targets,
    complete_daily_buckets,
    coverage_need,
    force_x_refresh,
    harvest_week_range,
    kind_tables,
    min_days_for,
    roster_entity_ids,
    window_day_range,
)
from backend.windows.time import WINDOW_DAYS, last_weekly_as_of
from backend.x_client.client import XApiError, _client, fetch_recent_daily_counts

log = logging.getLogger("desinfo.x_sync")


def _build_handle_targets() -> dict[str, dict[str, list[str]]]:
    """Map x_handle -> {media_ids, politician_ids} (deduped API calls)."""
    out: dict[str, dict[str, list[str]]] = {}
    for m in load_media_roster().get("media") or []:
        mid = m.get("id")
        if not mid:
            continue
        for h in iter_x_handles(m):
            slot = out.setdefault(h, {"media_ids": [], "politician_ids": []})
            if mid not in slot["media_ids"]:
                slot["media_ids"].append(mid)
    for c in load_politicians_roster().get("candidates") or []:
        pid = c.get("id")
        if not pid:
            continue
        for h in iter_x_handles(c):
            slot = out.setdefault(h, {"media_ids": [], "politician_ids": []})
            if pid not in slot["politician_ids"]:
                slot["politician_ids"].append(pid)
    return out


def _handles_done_this_week(
    handle_targets: dict[str, dict[str, list[str]]],
) -> set[str]:
    """Skip only when this harvest week's daily buckets are already there."""
    if force_x_refresh():
        return set()
    start_day, end_day = harvest_week_range()
    need = min_days_for(7)
    done: set[str] = set()
    with db_session() as conn:
        for handle, targets in handle_targets.items():
            ids_ok = False
            for mid in targets.get("media_ids") or []:
                n = int(
                    conn.execute(
                        """
                        SELECT COUNT(*) AS n FROM media_posts_daily
                        WHERE media_id=? AND day>=? AND day<?
                        """,
                        (mid, start_day, end_day),
                    ).fetchone()["n"]
                    or 0
                )
                if n >= need:
                    ids_ok = True
                    break
            if not ids_ok:
                for pid in targets.get("politician_ids") or []:
                    n = int(
                        conn.execute(
                            """
                            SELECT COUNT(*) AS n FROM politician_posts_daily
                            WHERE politician_id=? AND day>=? AND day<?
                            """,
                            (pid, start_day, end_day),
                        ).fetchone()["n"]
                        or 0
                    )
                    if n >= need:
                        ids_ok = True
                        break
            if ids_ok:
                done.add(handle)
    return done


def _fetch_week(
    client: Any,
    handle: str,
    since: datetime,
    until: datetime,
) -> tuple[int, list[tuple[str, int]]] | None:
    result = fetch_recent_daily_counts(handle, since, until, client=client)
    if result is None:
        log.info("@%s: counts/recent unavailable — skip write", handle)
        return None
    _total, buckets = result
    filled = complete_daily_buckets(buckets, since, until)
    return sum(c for _, c in filled), filled


def _accumulate(
    filled: list[tuple[str, int]],
    week_total: int,
    media_ids: list[str],
    politician_ids: list[str],
    pending_media: dict[tuple[str, str], int],
    pending_pol: dict[tuple[str, str], int],
    pending_media_7d: dict[str, int],
    pending_pol_7d: dict[str, int],
) -> None:
    for mid in media_ids:
        pending_media_7d[mid] = pending_media_7d.get(mid, 0) + week_total
        for day, count in filled:
            key = (mid, day)
            pending_media[key] = pending_media.get(key, 0) + count
    for pid in politician_ids:
        pending_pol_7d[pid] = pending_pol_7d.get(pid, 0) + week_total
        for day, count in filled:
            key = (pid, day)
            pending_pol[key] = pending_pol.get(key, 0) + count


def _write_kind_daily_and_window(
    kind: str,
    entity_ids: list[str],
    *,
    window_key: str,
    total: int,
    buckets: list[tuple[str, int]],
    when: datetime,
) -> None:
    tables = kind_tables(kind)
    daily_rows = [
        (eid, day, int(count)) for eid in entity_ids for day, count in buckets
    ]
    window_rows = [
        (eid, window_key, int(total), when.isoformat()) for eid in entity_ids
    ]
    with db_session() as conn:
        if daily_rows:
            conn.executemany(
                f"""
                INSERT INTO {tables["daily"]}({tables["id_col"]}, day, post_count)
                VALUES (?, ?, ?)
                ON CONFLICT({tables["id_col"]}, day) DO UPDATE SET
                    post_count=excluded.post_count
                """,
                daily_rows,
            )
        conn.executemany(
            f"""
            INSERT INTO {tables["windows"]}({tables["id_col"]}, window_key, post_count, synced_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT({tables["id_col"]}, window_key) DO UPDATE SET
                post_count=excluded.post_count,
                synced_at=excluded.synced_at
            """,
            window_rows,
        )


def sync_all_post_counts(windows: list[str] | None = None) -> dict[str, Any]:
    """One GET /tweets/counts/recent per unique @handle. Longer windows = cascade."""
    settings = get_settings()
    handle_targets = _build_handle_targets()
    if not handle_targets:
        raise RuntimeError("Aucun x_handle dans media_roster.yml / politicians_roster.yml")

    windows = windows or list(settings.x_sync_windows) or ["7d"]
    api_windows = [w for w in windows if w == "7d"] or ["7d"]
    skipped = [w for w in windows if w != "7d"]
    if skipped:
        log.warning("skipping API sync for %s — use cascade instead", skipped)

    cut = last_weekly_as_of()
    since = cut - timedelta(days=7)
    until = cut
    synced: dict[str, dict[str, int]] = {w: {} for w in api_windows}
    errors: list[str] = []
    status = "ok"
    days_written = 0
    api_calls = 0
    skipped_handles = 0

    with _client() as client:
        for w in api_windows:
            log.info(
                "syncing posts window=%s cut=%s unique_handles=%s",
                w,
                cut.isoformat(),
                len(handle_targets),
            )
            already = _handles_done_this_week(handle_targets)
            pending_media: dict[tuple[str, str], int] = {}
            pending_pol: dict[tuple[str, str], int] = {}
            pending_media_7d: dict[str, int] = {}
            pending_pol_7d: dict[str, int] = {}

            for handle in sorted(handle_targets.keys()):
                targets = handle_targets[handle]
                media_ids = targets.get("media_ids") or []
                politician_ids = targets.get("politician_ids") or []
                if handle in already:
                    skipped_handles += 1
                    synced[w][handle] = 0
                    log.info("skip @%s (this harvest week already in daily store)", handle)
                    continue
                try:
                    fetched = _fetch_week(client, handle, since, until)
                    if fetched is None:
                        continue
                    week_total, filled = fetched
                    _accumulate(
                        filled,
                        week_total,
                        media_ids,
                        politician_ids,
                        pending_media,
                        pending_pol,
                        pending_media_7d,
                        pending_pol_7d,
                    )
                    synced[w][handle] = week_total
                    api_calls += 1
                    log.info(
                        "@%s → %s posts (counts/recent, %s days, media=%s pol=%s)",
                        handle,
                        week_total,
                        len(filled),
                        len(media_ids),
                        len(politician_ids),
                    )
                    time.sleep(0.3)
                except XApiError as e:
                    errors.append(f"{w}/@{handle}: {e.status} {e.detail}")
                    if e.status == 402:
                        status = "partial_credits_depleted"
                        log.error("credits depleted — stopping (partial sync kept)")
                        break
                    if e.status == 429:
                        log.warning("rate limit on @%s — sleep 60s", handle)
                        time.sleep(60)
                        try:
                            fetched = _fetch_week(client, handle, since, until)
                            if fetched is None:
                                continue
                            week_total, filled = fetched
                            _accumulate(
                                filled,
                                week_total,
                                media_ids,
                                politician_ids,
                                pending_media,
                                pending_pol,
                                pending_media_7d,
                                pending_pol_7d,
                            )
                            synced[w][handle] = week_total
                            api_calls += 1
                        except XApiError as e2:
                            errors.append(f"{w}/@{handle}: {e2.status} {e2.detail}")
                            if e2.status == 402:
                                status = "partial_credits_depleted"
                                break
                    else:
                        log.warning("skip @%s: %s", handle, e)
                except Exception as e:
                    errors.append(f"{w}/@{handle}: {e}")
                    log.exception("skip @%s", handle)

            by_media: dict[str, list[tuple[str, int]]] = defaultdict(list)
            for (mid, day), count in pending_media.items():
                by_media[mid].append((day, count))
            for mid, buckets in by_media.items():
                _write_kind_daily_and_window(
                    "media",
                    [mid],
                    window_key=w,
                    total=pending_media_7d.get(mid, 0),
                    buckets=buckets,
                    when=cut,
                )
                days_written += len(buckets)
            by_pol: dict[str, list[tuple[str, int]]] = defaultdict(list)
            for (pid, day), count in pending_pol.items():
                by_pol[pid].append((day, count))
            for pid, buckets in by_pol.items():
                _write_kind_daily_and_window(
                    "politicians",
                    [pid],
                    window_key=w,
                    total=pending_pol_7d.get(pid, 0),
                    buckets=buckets,
                    when=cut,
                )
                days_written += len(buckets)

    stamp = cut.isoformat()
    if api_calls > 0:
        with db_session() as conn:
            set_meta(conn, "last_x_sync_at", stamp)
            set_meta(conn, "last_x_sync_status", status)
            set_meta(conn, "last_x_sync_politicians_at", stamp)
            set_meta(conn, "last_x_sync_politicians_status", status)
    elif skipped_handles and not errors:
        status = "skipped_already_this_week"

    sample = synced.get("7d") or synced.get(api_windows[0]) or {}
    result = {
        "status": status,
        "synced_at": stamp,
        "windows": api_windows,
        "unique_handles": len(handle_targets),
        "api_calls": api_calls,
        "skipped_handles": skipped_handles,
        "synced_handles": {w: len(synced[w]) for w in api_windows},
        "days_written": days_written,
        "sample": {h: sample[h] for h in list(sample)[:8]},
        "errors": errors[:10],
        "cost_hint_usd": round(api_calls * 0.005, 3),
    }
    log.info("x sync (unified) done: %s", result)
    return result


def _cascade_kind(kind: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Sum daily buckets into 30/90/365. First write needs coverage; later updates keep going."""
    now = now or last_weekly_as_of()
    need = coverage_need()
    targets = cascade_targets()
    if not targets:
        return {"status": "skip", "reason": "no cascade windows"}

    tables = kind_tables(kind)
    entity_ids = roster_entity_ids(kind)
    if not entity_ids:
        return {"status": "empty", "reason": "empty roster"}

    stamp = now.isoformat()
    out: dict[str, Any] = {"status": "ok", "windows": {}, "coverage_need": need}
    label = "politicians" if kind == "politicians" else "media"

    with db_session() as conn:
        for w in targets:
            days = WINDOW_DAYS[w]
            start_day, end_day = window_day_range(days, now)
            need_days = min_days_for(days, need)
            written = 0
            skipped_cov = 0

            for eid in entity_ids:
                row = conn.execute(
                    f"""
                    SELECT COUNT(*) AS n, COALESCE(SUM(post_count), 0) AS total
                    FROM {tables["daily"]}
                    WHERE {tables["id_col"]}=? AND day>=? AND day<?
                    """,
                    (eid, start_day, end_day),
                ).fetchone()
                n_days = int(row["n"] or 0)
                total = int(row["total"] or 0)
                existing = conn.execute(
                    f"""
                    SELECT 1 FROM {tables["windows"]}
                    WHERE {tables["id_col"]}=? AND window_key=?
                    """,
                    (eid, w),
                ).fetchone()
                if n_days < need_days and not existing:
                    skipped_cov += 1
                    continue
                conn.execute(
                    f"""
                    INSERT INTO {tables["windows"]}({tables["id_col"]}, window_key, post_count, synced_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT({tables["id_col"]}, window_key) DO UPDATE SET
                        post_count=excluded.post_count,
                        synced_at=excluded.synced_at
                    """,
                    (eid, w, total, stamp),
                )
                written += 1

            out["windows"][w] = {
                "written": written,
                "skipped_low_coverage": skipped_cov,
                "min_days": need_days,
                "range": [start_day, end_day],
            }
            log.info(
                "cascade %s %s: written=%s skipped=%s min_days=%s",
                label,
                w,
                written,
                skipped_cov,
                need_days,
            )

        set_meta(conn, tables["meta_cascade"], stamp)

    return out


def cascade_longer_windows(*, now: datetime | None = None) -> dict[str, Any]:
    """Derive 30d/90d/365d post counts from media_posts_daily — zero X API cost."""
    return _cascade_kind("media", now=now)


def cascade_politician_windows(*, now: datetime | None = None) -> dict[str, Any]:
    """Derive 30d/90d/365d politician post counts — zero X API cost."""
    return _cascade_kind("politicians", now=now)


def run_weekly_harvest() -> dict[str, Any]:
    """Weekly job: unified 7d counts/recent → cascade médias + candidats."""
    sync_res = sync_all_post_counts(windows=["7d"])
    return {
        "sync": sync_res,
        "cascade": cascade_longer_windows(),
        "politicians_cascade": cascade_politician_windows(),
    }
