"""Orchestrate ingest — stream shards to limit disk use."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from backend.config import get_settings
from backend.db import db_session, init_db, set_meta
from backend.ingest.attribute import attribute_notes
from backend.ingest.download import (
    download_and_extract_shard,
    http_client,
    iter_shard_urls,
    resolve_dump_day,
)
from backend.ingest.parse import load_helpful_ids, upsert_notes
from backend.politicians.attribute import attribute_politicians

log = logging.getLogger("desinfo.ingest")


def run_ingest(*, skip_download: bool = False, keep_raw: bool = False) -> dict:
    settings = get_settings()
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    init_db()

    if skip_download:
        return _ingest_from_existing_tsv(keep_raw=keep_raw)

    out = settings.raw_dir
    with http_client() as client:
        day = resolve_dump_day(client)
        log.info("using CN dump date %s", day.isoformat())
        (out / "DUMP_DATE.txt").write_text(day.isoformat() + "\n", encoding="utf-8")

        # 1) status shards → helpful set → delete
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

        # 2) notes shards one-by-one → upsert helpful → delete
        total = 0
        with db_session() as conn:
            for i, url in enumerate(iter_shard_urls(day, "notes", "notes")):
                tsv_name = f"notes-{i:05d}.tsv"
                path = download_and_extract_shard(url, out, tsv_name, client)
                if path is None:
                    if i == 0:
                        raise RuntimeError(f"Missing notes dump for {day}")
                    break
                total += upsert_notes(conn, [path], helpful_ids)
                if not keep_raw:
                    path.unlink(missing_ok=True)

            links = attribute_notes(conn)
            politician_links = attribute_politicians(conn)
            now = datetime.now(timezone.utc).isoformat()
            set_meta(conn, "last_ingest_at", now)
            set_meta(conn, "dump_date", day.isoformat())
            result = {
                "dump_date": day.isoformat(),
                "notes_helpful": total,
                "helpful_ids": len(helpful_ids),
                "note_media_links": links,
                "note_politician_links": politician_links,
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
        total = upsert_notes(conn, notes, helpful_ids)
        links = attribute_notes(conn)
        politician_links = attribute_politicians(conn)
        now = datetime.now(timezone.utc).isoformat()
        set_meta(conn, "last_ingest_at", now)
        result = {
            "notes_helpful": total,
            "helpful_ids": len(helpful_ids),
            "note_media_links": links,
            "note_politician_links": politician_links,
            "last_ingest_at": now,
        }
    if not keep_raw:
        for p in notes + statuses:
            p.unlink(missing_ok=True)
    return result
