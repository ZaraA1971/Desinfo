"""Sync post counts from X API (7d cheap) + cascade longer windows from daily store."""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.config import get_settings
from backend.db import db_session, set_meta
from backend.media_config import load_media_roster
from backend.politicians.config import load_politicians_roster
from backend.scoring.rank import WINDOW_DAYS
from backend.x_client.client import XApiError, _client, fetch_recent_daily_counts

log = logging.getLogger("desinfo.x_sync")


def sync_roster_post_counts(windows: list[str] | None = None) -> dict[str, Any]:
    """
    API sync — only cheap 7d counts/recent (stores daily buckets + window 7d).
    Longer windows must use cascade_longer_windows() (no API).
    """
    settings = get_settings()
    roster = load_media_roster()
    media_list = roster.get("media") or []
    windows = windows or list(settings.x_sync_windows) or ["7d"]
    # Force API path to 7d only — never timeline-burn longer windows here
    api_windows = [w for w in windows if w == "7d"]
    if not api_windows:
        api_windows = ["7d"]
    skipped = [w for w in windows if w != "7d"]
    if skipped:
        log.warning("skipping API sync for %s — use cascade instead", skipped)

    handle_to_media: dict[str, list[str]] = defaultdict(list)
    id_to_handle: dict[str, str] = {}
    for m in media_list:
        h = (m.get("x_handle") or "").lstrip("@").strip()
        mid = m.get("id")
        if h and mid:
            handle_to_media[h].append(mid)
            id_to_handle[mid] = h

    if not handle_to_media:
        raise RuntimeError("Aucun x_handle dans media_roster.yml")

    until = datetime.now(timezone.utc)
    synced: dict[str, dict[str, int]] = {w: {} for w in api_windows}
    errors: list[str] = []
    status = "ok"
    days_written = 0

    with _client() as client:
        for w in api_windows:
            days = WINDOW_DAYS[w]
            since = until - timedelta(days=days)
            log.info("syncing posts window=%s days=%s handles=%s", w, days, len(handle_to_media))
            already = _already_synced(w, id_to_handle, max_age_hours=6)
            # Don't skip if we have no daily history yet (need buckets for cascade)
            with db_session() as conn:
                daily_n = int(
                    conn.execute("SELECT COUNT(*) AS n FROM media_posts_daily").fetchone()["n"]
                )
            if daily_n == 0:
                already = {}
                log.info("media_posts_daily empty — forcing full 7d refresh")

            for handle in sorted(handle_to_media.keys()):
                if handle in already:
                    n = already[handle]
                    synced[w][handle] = n
                    log.info("skip @%s (cached %s for %s)", handle, n, w)
                    continue
                try:
                    result = fetch_recent_daily_counts(handle, since, until, client=client)
                    if result is None:
                        log.info("@%s: counts unavailable — skip write", handle)
                        continue
                    total, buckets = result
                    _write_daily_and_window(
                        handle_to_media[handle],
                        window_key=w,
                        total=total,
                        buckets=buckets,
                        when=until,
                    )
                    days_written += len(buckets) * len(handle_to_media[handle])
                    synced[w][handle] = total
                    log.info("@%s → %s posts (counts/recent, %s days)", handle, total, len(buckets))
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
                            result = fetch_recent_daily_counts(handle, since, until, client=client)
                            if result is None:
                                continue
                            total, buckets = result
                            _write_daily_and_window(
                                handle_to_media[handle],
                                window_key=w,
                                total=total,
                                buckets=buckets,
                                when=until,
                            )
                            synced[w][handle] = total
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
            else:
                continue
            break  # broken due to 402

    with db_session() as conn:
        set_meta(conn, "last_x_sync_at", until.isoformat())
        set_meta(conn, "last_x_sync_status", status)

    sample = synced.get("7d") or synced.get(api_windows[0]) or {}
    result = {
        "status": status,
        "synced_at": until.isoformat(),
        "windows": api_windows,
        "synced_handles": {w: len(synced[w]) for w in api_windows},
        "days_written": days_written,
        "sample": {h: sample[h] for h in list(sample)[:8]},
        "errors": errors[:10],
    }
    log.info("x sync done: %s", result)
    return result


def cascade_longer_windows(*, now: datetime | None = None) -> dict[str, Any]:
    """
    Derive 30d/90d/365d post counts from media_posts_daily — zero X API cost.
    Only writes a window when day coverage in that range >= DESINFO_CASCADE_COVERAGE.
    """
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    coverage_need = max(0.1, min(1.0, settings.cascade_coverage))
    targets = [w for w in settings.cascade_windows if w in WINDOW_DAYS and w != "7d"]
    if not targets:
        return {"status": "skip", "reason": "no cascade windows"}

    stamp = now.isoformat()
    out: dict[str, Any] = {"status": "ok", "windows": {}, "coverage_need": coverage_need}

    with db_session() as conn:
        media_ids = [
            r["media_id"]
            for r in conn.execute("SELECT DISTINCT media_id FROM media_posts_daily").fetchall()
        ]
        if not media_ids:
            # also try roster media even without daily yet
            return {"status": "empty", "reason": "no daily rows yet"}

        for w in targets:
            days = WINDOW_DAYS[w]
            start_day = (now - timedelta(days=days)).strftime("%Y-%m-%d")
            end_day = now.strftime("%Y-%m-%d")
            min_days = max(1, int(days * coverage_need))
            written = 0
            skipped_cov = 0

            for mid in media_ids:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS n, COALESCE(SUM(post_count), 0) AS total
                    FROM media_posts_daily
                    WHERE media_id=? AND day>=? AND day<=?
                    """,
                    (mid, start_day, end_day),
                ).fetchone()
                n_days = int(row["n"] or 0)
                total = int(row["total"] or 0)
                if n_days < min_days:
                    skipped_cov += 1
                    continue
                conn.execute(
                    """
                    INSERT INTO media_post_windows(media_id, window_key, post_count, synced_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(media_id, window_key) DO UPDATE SET
                        post_count=excluded.post_count,
                        synced_at=excluded.synced_at
                    """,
                    (mid, w, total, stamp),
                )
                written += 1

            out["windows"][w] = {
                "written": written,
                "skipped_low_coverage": skipped_cov,
                "min_days": min_days,
                "range": [start_day, end_day],
            }
            log.info(
                "cascade %s: written=%s skipped=%s min_days=%s",
                w,
                written,
                skipped_cov,
                min_days,
            )

        set_meta(conn, "last_cascade_at", stamp)

    return out


def sync_politicians_post_counts(windows: list[str] | None = None) -> dict[str, Any]:
    """
    API sync for politicians — mirrors sync_roster_post_counts (media): cheap 7d
    counts/recent only (stores daily buckets + window 7d). Longer windows must
    use cascade_politician_windows() (no API).
    """
    settings = get_settings()
    roster = load_politicians_roster()
    candidates = roster.get("candidates") or []
    windows = windows or list(settings.x_sync_windows) or ["7d"]
    api_windows = [w for w in windows if w == "7d"]
    if not api_windows:
        api_windows = ["7d"]
    skipped = [w for w in windows if w != "7d"]
    if skipped:
        log.warning("skipping politicians API sync for %s — use cascade instead", skipped)

    handle_to_politician: dict[str, list[str]] = defaultdict(list)
    id_to_handle: dict[str, str] = {}
    for c in candidates:
        h = (c.get("x_handle") or "").lstrip("@").strip()
        pid = c.get("id")
        if h and pid:
            handle_to_politician[h].append(pid)
            id_to_handle[pid] = h

    if not handle_to_politician:
        raise RuntimeError("Aucun x_handle dans politicians_roster.yml")

    until = datetime.now(timezone.utc)
    synced: dict[str, dict[str, int]] = {w: {} for w in api_windows}
    errors: list[str] = []
    status = "ok"
    days_written = 0

    with _client() as client:
        for w in api_windows:
            days = WINDOW_DAYS[w]
            since = until - timedelta(days=days)
            log.info(
                "syncing politician posts window=%s days=%s handles=%s",
                w,
                days,
                len(handle_to_politician),
            )
            already = _already_synced_politicians(w, id_to_handle, max_age_hours=6)
            with db_session() as conn:
                daily_n = int(
                    conn.execute(
                        "SELECT COUNT(*) AS n FROM politician_posts_daily"
                    ).fetchone()["n"]
                )
            if daily_n == 0:
                already = {}
                log.info("politician_posts_daily empty — forcing full 7d refresh")

            for handle in sorted(handle_to_politician.keys()):
                if handle in already:
                    n = already[handle]
                    synced[w][handle] = n
                    log.info("skip @%s (cached %s for %s)", handle, n, w)
                    continue
                try:
                    result = fetch_recent_daily_counts(handle, since, until, client=client)
                    if result is None:
                        log.info("@%s: counts unavailable — skip write", handle)
                        continue
                    total, buckets = result
                    _write_politician_daily_and_window(
                        handle_to_politician[handle],
                        window_key=w,
                        total=total,
                        buckets=buckets,
                        when=until,
                    )
                    days_written += len(buckets) * len(handle_to_politician[handle])
                    synced[w][handle] = total
                    log.info("@%s → %s posts (counts/recent, %s days)", handle, total, len(buckets))
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
                            result = fetch_recent_daily_counts(handle, since, until, client=client)
                            if result is None:
                                continue
                            total, buckets = result
                            _write_politician_daily_and_window(
                                handle_to_politician[handle],
                                window_key=w,
                                total=total,
                                buckets=buckets,
                                when=until,
                            )
                            synced[w][handle] = total
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
            else:
                continue
            break  # broken due to 402

    with db_session() as conn:
        set_meta(conn, "last_x_sync_politicians_at", until.isoformat())
        set_meta(conn, "last_x_sync_politicians_status", status)

    sample = synced.get("7d") or synced.get(api_windows[0]) or {}
    result = {
        "status": status,
        "synced_at": until.isoformat(),
        "windows": api_windows,
        "synced_handles": {w: len(synced[w]) for w in api_windows},
        "days_written": days_written,
        "sample": {h: sample[h] for h in list(sample)[:8]},
        "errors": errors[:10],
    }
    log.info("x sync (politicians) done: %s", result)
    return result


def cascade_politician_windows(*, now: datetime | None = None) -> dict[str, Any]:
    """
    Derive 30d/90d/365d politician post counts from politician_posts_daily —
    zero X API cost. Mirrors cascade_longer_windows() (media).
    """
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    coverage_need = max(0.1, min(1.0, settings.cascade_coverage))
    targets = [w for w in settings.cascade_windows if w in WINDOW_DAYS and w != "7d"]
    if not targets:
        return {"status": "skip", "reason": "no cascade windows"}

    stamp = now.isoformat()
    out: dict[str, Any] = {"status": "ok", "windows": {}, "coverage_need": coverage_need}

    with db_session() as conn:
        politician_ids = [
            r["politician_id"]
            for r in conn.execute(
                "SELECT DISTINCT politician_id FROM politician_posts_daily"
            ).fetchall()
        ]
        if not politician_ids:
            return {"status": "empty", "reason": "no daily rows yet"}

        for w in targets:
            days = WINDOW_DAYS[w]
            start_day = (now - timedelta(days=days)).strftime("%Y-%m-%d")
            end_day = now.strftime("%Y-%m-%d")
            min_days = max(1, int(days * coverage_need))
            written = 0
            skipped_cov = 0

            for pid in politician_ids:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS n, COALESCE(SUM(post_count), 0) AS total
                    FROM politician_posts_daily
                    WHERE politician_id=? AND day>=? AND day<=?
                    """,
                    (pid, start_day, end_day),
                ).fetchone()
                n_days = int(row["n"] or 0)
                total = int(row["total"] or 0)
                if n_days < min_days:
                    skipped_cov += 1
                    continue
                conn.execute(
                    """
                    INSERT INTO politician_post_windows(politician_id, window_key, post_count, synced_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(politician_id, window_key) DO UPDATE SET
                        post_count=excluded.post_count,
                        synced_at=excluded.synced_at
                    """,
                    (pid, w, total, stamp),
                )
                written += 1

            out["windows"][w] = {
                "written": written,
                "skipped_low_coverage": skipped_cov,
                "min_days": min_days,
                "range": [start_day, end_day],
            }
            log.info(
                "cascade politicians %s: written=%s skipped=%s min_days=%s",
                w,
                written,
                skipped_cov,
                min_days,
            )

        set_meta(conn, "last_cascade_politicians_at", stamp)

    return out


def run_weekly_harvest() -> dict[str, Any]:
    """Weekly job: 7d API sync → cascade → ready for scoring (media + politicians)."""
    sync_res = sync_roster_post_counts(windows=["7d"])
    cascade_res = cascade_longer_windows()
    politicians_sync_res = sync_politicians_post_counts(windows=["7d"])
    politicians_cascade_res = cascade_politician_windows()
    return {
        "sync": sync_res,
        "cascade": cascade_res,
        "politicians_sync": politicians_sync_res,
        "politicians_cascade": politicians_cascade_res,
    }


def _write_daily_and_window(
    media_ids: list[str],
    *,
    window_key: str,
    total: int,
    buckets: list[tuple[str, int]],
    when: datetime,
) -> None:
    daily_rows = [
        (media_id, day, int(count))
        for media_id in media_ids
        for day, count in buckets
    ]
    window_rows = [
        (media_id, window_key, int(total), when.isoformat())
        for media_id in media_ids
    ]
    with db_session() as conn:
        if daily_rows:
            conn.executemany(
                """
                INSERT INTO media_posts_daily(media_id, day, post_count)
                VALUES (?, ?, ?)
                ON CONFLICT(media_id, day) DO UPDATE SET
                    post_count=excluded.post_count
                """,
                daily_rows,
            )
        conn.executemany(
            """
            INSERT INTO media_post_windows(media_id, window_key, post_count, synced_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(media_id, window_key) DO UPDATE SET
                post_count=excluded.post_count,
                synced_at=excluded.synced_at
            """,
            window_rows,
        )


def _already_synced(
    window_key: str,
    id_to_handle: dict[str, str],
    max_age_hours: int = 6,
) -> dict[str, int]:
    """Map handle -> post_count for rows synced recently."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    out: dict[str, int] = {}
    with db_session() as conn:
        rows = conn.execute(
            "SELECT media_id, post_count, synced_at FROM media_post_windows WHERE window_key=?",
            (window_key,),
        ).fetchall()
        for r in rows:
            try:
                ts = datetime.fromisoformat(r["synced_at"])
            except Exception:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < cutoff:
                continue
            h = id_to_handle.get(r["media_id"])
            if h:
                out[h] = int(r["post_count"])
    return out


def _write_politician_daily_and_window(
    politician_ids: list[str],
    *,
    window_key: str,
    total: int,
    buckets: list[tuple[str, int]],
    when: datetime,
) -> None:
    daily_rows = [
        (politician_id, day, int(count))
        for politician_id in politician_ids
        for day, count in buckets
    ]
    window_rows = [
        (politician_id, window_key, int(total), when.isoformat())
        for politician_id in politician_ids
    ]
    with db_session() as conn:
        if daily_rows:
            conn.executemany(
                """
                INSERT INTO politician_posts_daily(politician_id, day, post_count)
                VALUES (?, ?, ?)
                ON CONFLICT(politician_id, day) DO UPDATE SET
                    post_count=excluded.post_count
                """,
                daily_rows,
            )
        conn.executemany(
            """
            INSERT INTO politician_post_windows(politician_id, window_key, post_count, synced_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(politician_id, window_key) DO UPDATE SET
                post_count=excluded.post_count,
                synced_at=excluded.synced_at
            """,
            window_rows,
        )


def _already_synced_politicians(
    window_key: str,
    id_to_handle: dict[str, str],
    max_age_hours: int = 6,
) -> dict[str, int]:
    """Map handle -> post_count for politician window rows synced recently."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    out: dict[str, int] = {}
    with db_session() as conn:
        rows = conn.execute(
            "SELECT politician_id, post_count, synced_at FROM politician_post_windows WHERE window_key=?",
            (window_key,),
        ).fetchall()
        for r in rows:
            try:
                ts = datetime.fromisoformat(r["synced_at"])
            except Exception:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < cutoff:
                continue
            h = id_to_handle.get(r["politician_id"])
            if h:
                out[h] = int(r["post_count"])
    return out
