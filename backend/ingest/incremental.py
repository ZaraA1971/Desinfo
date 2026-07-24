"""Incremental CN dump day selection — only ingest dumps not yet processed."""
from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

from backend.config import get_settings
from backend.ingest.download import resolve_dump_day

log = logging.getLogger("desinfo.ingest.incremental")


def parse_dump_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def list_incremental_dump_days(
    client: httpx.Client,
    last_dump_date: date | None,
) -> list[date]:
    """
    Dump days to ingest since last_dump_date (exclusive) through latest available.
    First run: latest dump only. Up-to-date: [].
    """
    latest = resolve_dump_day(client)
    if last_dump_date is None:
        log.info("first ingest — latest dump %s", latest.isoformat())
        return [latest]
    if last_dump_date >= latest:
        log.info("CN dump up to date (last=%s latest=%s)", last_dump_date, latest)
        return []

    days: list[date] = []
    d = last_dump_date
    from datetime import timedelta

    d = d + timedelta(days=1)
    while d <= latest:
        try:
            resolve_dump_day(client, d)
            days.append(d)
        except RuntimeError:
            log.warning("skip missing dump day %s", d.isoformat())
        d = d + timedelta(days=1)
    log.info("incremental dump days: %s → %s (%s days)", last_dump_date, latest, len(days))
    return days


def roster_config_hash() -> str:
    """Hash attribution config — full re-attribute when rosters change."""
    settings = get_settings()
    parts: list[bytes] = []
    for path in (
        settings.media_domains_path,
        settings.politicians_roster_path,
    ):
        if path.exists():
            parts.append(path.read_bytes())
    if not parts:
        return ""
    return hashlib.sha256(b"".join(parts)).hexdigest()[:16]


def ingest_stamp() -> str:
    return datetime.now(timezone.utc).isoformat()
