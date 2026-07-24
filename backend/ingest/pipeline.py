"""Orchestrate ingest — incremental dump days, incremental attribution."""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from backend.config import get_settings
from backend.db import db_session, get_meta, init_db, set_meta
from backend.ingest.attribute import attribute_notes
from backend.ingest.download import (
    download_and_extract_shard,
    http_client,
    iter_shard_urls,
    resolve_dump_day,
)
from backend.ingest.incremental import (
    ingest_stamp,
    list_incremental_dump_days,
    parse_dump_date,
    roster_config_hash,
)
from backend.ingest.parse import load_helpful_ids, upsert_notes
from backend.politicians.attribute import attribute_politicians

log = logging.getLogger("desinfo.ingest")


def _ingest_dump_day(
    conn,
    client,
    day: date,
    out: Path,
    *,
    keep_raw: bool,
) -> tuple[int, set[str]]:
    """Download + parse one CN dump day. Returns (upsert_count, note_ids)."""
    log.info("ingesting CN dump %s", day.isoformat())
    (out / "DUMP_DATE.txt").write_text(day.isoformat() + "\n", encoding="utf-8")

    status_paths: list[Path] = []
    for i, url in enumerate(iter_shard_urls(day, "noteStatusHistory", "noteStatusHistory")):
        tsv_name = f"noteStatusHistory-{i:05d}.tsv"
        path = download_and_extract_shard(url, out, tsv_name, client)
        if path is None:
            if i == 0:
                raise RuntimeError(f"Missing status dump for {day}")
            break
        status_paths.append(path)

    helpful_ids = load_helpful_ids(status_paths)
    if not keep_raw:
        for p in status_paths:
            p.unlink(missing_ok=True)

    total = 0
    touched: set[str] = set()
    for i, url in enumerate(iter_shard_urls(day, "notes", "notes")):
        tsv_name = f"notes-{i:05d}.tsv"
        path = download_and_extract_shard(url, out, tsv_name, client)
        if path is None:
            if i == 0:
                raise RuntimeError(f"Missing notes dump for {day}")
            break
        n, ids = upsert_notes(conn, [path], helpful_ids)
        total += n
        touched |= ids
        if not keep_raw:
            path.unlink(missing_ok=True)

    return total, touched


def run_ingest(
    *,
    skip_download: bool = False,
    keep_raw: bool = False,
    full: bool = False,
) -> dict:
    """
    Incremental CN ingest: only new dump days since last_dump_date.
    Attribution: only notes touched this run (full rebuild if roster hash changes).
    """
    settings = get_settings()
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    init_db()

    if skip_download:
        return _ingest_from_existing_tsv(keep_raw=keep_raw)

    out = settings.raw_dir
    with db_session() as conn:
        last_dump = parse_dump_date(get_meta(conn, "last_dump_date"))
        if last_dump is None:
            # migrate legacy meta
            last_dump = parse_dump_date(get_meta(conn, "dump_date"))
        prev_roster_hash = get_meta(conn, "roster_config_hash") or ""

    with http_client() as client:
        if full:
            days = [resolve_dump_day(client)]
            log.info("full ingest requested — dump %s", days[0].isoformat())
        else:
            days = list_incremental_dump_days(client, last_dump)

        if not days:
            now = ingest_stamp()
            with db_session() as conn:
                set_meta(conn, "last_ingest_at", now)
                if last_dump and not get_meta(conn, "last_dump_date"):
                    set_meta(conn, "last_dump_date", last_dump.isoformat())
            return {
                "status": "skipped",
                "reason": "no new dump days",
                "last_dump_date": last_dump.isoformat() if last_dump else None,
                "last_ingest_at": now,
            }

        total_upserted = 0
        all_touched: set[str] = set()
        last_day = days[-1]

        with db_session() as conn:
            for day in days:
                n, ids = _ingest_dump_day(conn, client, day, out, keep_raw=keep_raw)
                total_upserted += n
                all_touched |= ids

            roster_hash = roster_config_hash()
            rebuild = full or (roster_hash and roster_hash != prev_roster_hash)
            if rebuild:
                log.info("roster config changed — full re-attribute")
                links = attribute_notes(conn, rebuild=True)
                politician_links = attribute_politicians(conn, rebuild=True)
            elif all_touched:
                links = attribute_notes(conn, note_ids=all_touched)
                politician_links = attribute_politicians(conn, note_ids=all_touched)
            else:
                links = 0
                politician_links = 0

            now = ingest_stamp()
            set_meta(conn, "last_ingest_at", now)
            set_meta(conn, "last_dump_date", last_day.isoformat())
            set_meta(conn, "dump_date", last_day.isoformat())
            if roster_hash:
                set_meta(conn, "roster_config_hash", roster_hash)

            result = {
                "status": "ok",
                "dump_days": [d.isoformat() for d in days],
                "dump_date": last_day.isoformat(),
                "notes_upserted": total_upserted,
                "notes_touched": len(all_touched),
                "touched_note_ids": sorted(all_touched),
                "helpful_ids": len(all_touched),
                "note_media_links": links,
                "note_politician_links": politician_links,
                "incremental": not full,
                "rebuild_attribute": rebuild,
                "last_ingest_at": now,
            }

    log.info("ingest done: %s", result)
    return result


def _ingest_from_existing_tsv(*, keep_raw: bool) -> dict:
    settings = get_settings()
    notes = sorted(settings.raw_dir.glob("notes-*.tsv"))
    statuses = sorted(settings.raw_dir.glob("noteStatusHistory-*.tsv"))
    if not notes or not statuses:
        raise RuntimeError("skip_download but no TSV in data/raw/")
    helpful_ids = load_helpful_ids(statuses)
    with db_session() as conn:
        total, touched = upsert_notes(conn, notes, helpful_ids)
        links = attribute_notes(conn, note_ids=touched if touched else None)
        politician_links = attribute_politicians(conn, note_ids=touched if touched else None)
        now = ingest_stamp()
        set_meta(conn, "last_ingest_at", now)
        result = {
            "status": "ok",
            "notes_upserted": total,
            "notes_touched": len(touched),
            "note_media_links": links,
            "note_politician_links": politician_links,
            "last_ingest_at": now,
        }
    if not keep_raw:
        for p in notes + statuses:
            p.unlink(missing_ok=True)
    return result
