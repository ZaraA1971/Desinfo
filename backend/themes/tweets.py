"""Tweet text cache for theme classification context."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from backend.config import get_settings
from backend.db import db_session
from backend.x_client.client import XApiNotConfigured, fetch_tweets_by_ids

log = logging.getLogger("desinfo.themes.tweets")


def cached_tweet_texts(tweet_ids: list[str]) -> dict[str, str | None]:
    """Return {tweet_id: text|None} from local cache only."""
    ids = [str(t).strip() for t in tweet_ids if str(t).strip()]
    if not ids:
        return {}
    out: dict[str, str | None] = {}
    with db_session() as conn:
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT tweet_id, text, status FROM tweets WHERE tweet_id IN ({placeholders})",
            ids,
        ).fetchall()
    for r in rows:
        out[r["tweet_id"]] = r["text"] if r["status"] == "ok" else None
    return out


def ensure_tweet_texts(tweet_ids: list[str]) -> dict[str, str | None]:
    """Return tweet texts, optionally fetching missing ids from X API and caching them.

    Mode via DESINFO_THEME_X_FETCH:
    - never: note-only classification (0 X cost)
    - cache_only (default): cache hit only, no API for missing
    - fetch: batch GET /2/tweets for missing ids ($0.005/tweet, dedup daily)
    """
    settings = get_settings()
    mode = settings.theme_x_fetch
    ids = list(dict.fromkeys(str(t).strip() for t in tweet_ids if str(t).strip()))
    if not ids:
        return {}

    if mode == "never":
        return {tid: None for tid in ids}

    cached = cached_tweet_texts(ids)
    if mode == "cache_only":
        return {tid: cached.get(tid) for tid in ids}

    missing = [tid for tid in ids if tid not in cached]
    if not missing:
        return {tid: cached.get(tid) for tid in ids}

    try:
        fetched = fetch_tweets_by_ids(missing)
    except XApiNotConfigured:
        log.warning("X API not configured — classifying without post text")
        return {tid: cached.get(tid) for tid in ids}
    except Exception:
        log.exception("tweet fetch failed")
        return {tid: cached.get(tid) for tid in ids}

    now = datetime.now(timezone.utc).isoformat()
    rows: list[tuple[Any, ...]] = []
    for tid, payload in fetched.items():
        status = payload.get("status") or "missing"
        text = payload.get("text")
        lang = payload.get("lang")
        rows.append((tid, text, lang, now, status))
        cached[tid] = text if status == "ok" else None

    if rows:
        with db_session() as conn:
            conn.executemany(
                """
                INSERT INTO tweets(tweet_id, text, lang, fetched_at, status)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tweet_id) DO UPDATE SET
                    text=excluded.text,
                    lang=excluded.lang,
                    fetched_at=excluded.fetched_at,
                    status=excluded.status
                """,
                rows,
            )
        log.info("cached %s tweets (%s missing/error)", len(rows), sum(1 for r in rows if r[4] != "ok"))

    return {tid: cached.get(tid) for tid in ids}
