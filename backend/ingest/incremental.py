"""Incremental CN dump day selection — only ingest dumps not yet processed."""
from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timedelta, timezone

import httpx

from backend.config import get_settings
from backend.ingest.download import dump_day_ready, latest_dump_day

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
    Dump days to ingest since last_dump_date (exclusive) through today.
    First run: latest ready dump only. Already up to date / nothing new: [].
    Missing or incomplete days are skipped — never raises for a publication gap.
    """
    today = datetime.now(timezone.utc).date()
    if last_dump_date is None:
        latest = latest_dump_day(client)
        if latest is None:
            raise RuntimeError("No CN dump day found (first ingest)")
        log.info("first ingest — latest dump %s", latest.isoformat())
        return [latest]

    days: list[date] = []
    d = last_dump_date + timedelta(days=1)
    while d <= today:
        if dump_day_ready(client, d):
            days.append(d)
        else:
            log.warning("skip missing dump day %s", d.isoformat())
        d += timedelta(days=1)

    if not days:
        log.info("CN dump up to date or no new ready day (last=%s today=%s)", last_dump_date, today)
        return []

    log.info(
        "incremental dump days: %s → %s (%s days)",
        last_dump_date,
        days[-1],
        len(days),
    )
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
