"""X API v2 client — user lookup + efficient post counts."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from backend.config import get_settings

log = logging.getLogger("desinfo.x_client")

API_BASE = "https://api.x.com/2"


class XApiNotConfigured(RuntimeError):
    """Raised when post counts are requested without API credentials."""


class XApiError(RuntimeError):
    """Raised on X API HTTP / business errors (incl. credits depleted)."""

    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(f"X API {status}: {detail}")


def _client() -> httpx.Client:
    settings = get_settings()
    if not settings.x_bearer_token:
        raise XApiNotConfigured("X_BEARER_TOKEN manquant dans .env")
    return httpx.Client(
        base_url=API_BASE,
        headers={"Authorization": f"Bearer {settings.x_bearer_token}"},
        timeout=httpx.Timeout(60.0, connect=20.0),
        follow_redirects=True,
    )


def _raise_for_api(resp: httpx.Response) -> None:
    if resp.status_code < 400:
        return
    detail = resp.text[:500]
    try:
        payload = resp.json()
        detail = payload.get("detail") or payload.get("title") or detail
    except Exception:
        pass
    raise XApiError(resp.status_code, str(detail))


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def lookup_user_id(username: str, client: httpx.Client | None = None) -> str | None:
    handle = username.lstrip("@").strip()
    if not handle:
        return None
    own = client is None
    c = client or _client()
    try:
        resp = c.get(f"/users/by/username/{handle}", params={"user.fields": "id,username"})
        if resp.status_code == 404:
            return None
        # empty data without 404
        _raise_for_api(resp)
        data = resp.json().get("data")
        if not data:
            return None
        return data.get("id")
    finally:
        if own:
            c.close()


def count_via_search_counts(
    handle: str,
    since: datetime,
    until: datetime | None = None,
    *,
    client: httpx.Client,
) -> int | None:
    """Prefer /tweets/counts/recent (1 request, ~7d max). Returns total or None."""
    result = fetch_recent_daily_counts(handle, since, until, client=client)
    if result is None:
        return None
    return result[0]


def fetch_recent_daily_counts(
    handle: str,
    since: datetime,
    until: datetime | None = None,
    *,
    client: httpx.Client,
) -> tuple[int, list[tuple[str, int]]] | None:
    """
    /tweets/counts/recent with daily granularity.
    Returns (total, [(YYYY-MM-DD, count), ...]) or None if unavailable.
    Never call /tweets/counts/all — too expensive.
    """
    since = _as_utc(since)
    until = _as_utc(until) if until else datetime.now(timezone.utc)
    now = datetime.now(timezone.utc)
    if until > now - timedelta(seconds=30):
        until = now - timedelta(seconds=30)
    earliest = now - timedelta(days=7) + timedelta(minutes=2)
    if since < earliest:
        since = earliest
    if since >= until:
        since = until - timedelta(days=6, hours=23)
    days = (until - since).total_seconds() / 86400
    if days > 8:
        return None
    query = f"from:{handle} -is:retweet"
    params = {
        "query": query,
        "granularity": "day",
        "start_time": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_time": until.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    resp = client.get("/tweets/counts/recent", params=params)
    if resp.status_code in (400, 403, 404):
        log.info("counts/recent unavailable for @%s (%s)", handle, resp.status_code)
        return None
    _raise_for_api(resp)
    payload = resp.json()
    buckets: list[tuple[str, int]] = []
    for b in payload.get("data") or []:
        start = str(b.get("start") or "")
        day = start[:10] if len(start) >= 10 else ""
        if not day:
            continue
        buckets.append((day, int(b.get("tweet_count") or 0)))
    meta = payload.get("meta") or {}
    if "total_tweet_count" in meta:
        total = int(meta["total_tweet_count"])
    else:
        total = sum(c for _, c in buckets)
    return total, buckets


def count_handle_posts(
    handle: str,
    since: datetime,
    until: datetime | None = None,
    *,
    client: httpx.Client,
    allow_timeline_fallback: bool = True,
) -> int:
    """Count posts — prefer cheap counts/recent; timeline only if allowed."""
    handle = handle.lstrip("@").strip()
    n = count_via_search_counts(handle, since, until, client=client)
    if n is not None:
        log.info("@%s → %s posts (counts/recent)", handle, n)
        return n
    if not allow_timeline_fallback:
        log.warning("@%s: counts unavailable, no timeline fallback", handle)
        return 0
    settings = get_settings()
    if not settings.x_allow_timeline:
        log.warning("@%s: counts unavailable, timeline disabled (DESINFO_X_ALLOW_TIMELINE=0)", handle)
        return 0
    uid = lookup_user_id(handle, client=client)
    if not uid:
        log.warning("handle introuvable: @%s", handle)
        return 0
    n = count_user_posts_timeline(uid, since, until, client=client)
    log.info("@%s → %s posts (timeline)", handle, n)
    return n


def count_user_posts_timeline(
    user_id: str,
    since: datetime,
    until: datetime | None = None,
    *,
    client: httpx.Client,
    max_pages: int = 40,
) -> int:
    """Paginate user timeline. Excludes retweets only (keeps replies)."""
    since = _as_utc(since)
    until = _as_utc(until) if until else datetime.now(timezone.utc)
    params: dict[str, Any] = {
        "max_results": 100,
        "exclude": "retweets",
        "start_time": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_time": until.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tweet.fields": "created_at",
    }
    total = 0
    next_token: str | None = None
    pages = 0
    while pages < max_pages:
        p = dict(params)
        if next_token:
            p["pagination_token"] = next_token
        resp = client.get(f"/users/{user_id}/tweets", params=p)
        if resp.status_code == 429:
            reset = resp.headers.get("x-rate-limit-reset")
            wait = 15
            if reset and reset.isdigit():
                wait = max(1, int(reset) - int(time.time()) + 1)
            log.warning("rate limited, sleep %ss", wait)
            time.sleep(min(wait, 90))
            continue
        _raise_for_api(resp)
        payload = resp.json()
        batch = payload.get("data") or []
        total += len(batch)
        next_token = (payload.get("meta") or {}).get("next_token")
        pages += 1
        if not next_token:
            break
        time.sleep(0.25)
    return total


def fetch_tweets_by_ids(
    tweet_ids: list[str],
    *,
    client: httpx.Client | None = None,
) -> dict[str, dict[str, Any]]:
    """Batch-fetch tweet texts via GET /2/tweets (up to 100 ids / request).

    Returns {tweet_id: {"text": str|None, "lang": str|None, "status": "ok"|"missing"|"error"}}.
    """
    ids = [str(t).strip() for t in tweet_ids if str(t).strip()]
    out: dict[str, dict[str, Any]] = {
        tid: {"text": None, "lang": None, "status": "missing"} for tid in ids
    }
    if not ids:
        return out

    own = client is None
    c = client or _client()
    try:
        for i in range(0, len(ids), 100):
            chunk = ids[i : i + 100]
            resp = c.get(
                "/tweets",
                params={
                    "ids": ",".join(chunk),
                    "tweet.fields": "text,lang",
                },
            )
            if resp.status_code == 429:
                reset = resp.headers.get("x-rate-limit-reset")
                wait = 15
                if reset and reset.isdigit():
                    wait = max(1, int(reset) - int(time.time()) + 1)
                log.warning("tweets lookup rate limited, sleep %ss", wait)
                time.sleep(min(wait, 90))
                resp = c.get(
                    "/tweets",
                    params={"ids": ",".join(chunk), "tweet.fields": "text,lang"},
                )
            if resp.status_code >= 400:
                log.warning("tweets lookup failed %s: %s", resp.status_code, resp.text[:200])
                for tid in chunk:
                    out[tid] = {"text": None, "lang": None, "status": "error"}
                continue
            payload = resp.json()
            for tw in payload.get("data") or []:
                tid = str(tw.get("id") or "")
                if not tid:
                    continue
                out[tid] = {
                    "text": (tw.get("text") or "").strip() or None,
                    "lang": tw.get("lang"),
                    "status": "ok",
                }
            for err in payload.get("errors") or []:
                # {"resource_id": "...", "detail": "..."}
                rid = str(err.get("resource_id") or err.get("value") or "")
                if rid in out:
                    out[rid] = {"text": None, "lang": None, "status": "missing"}
            time.sleep(0.15)
    finally:
        if own:
            c.close()
    return out
