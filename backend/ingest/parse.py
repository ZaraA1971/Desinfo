"""Parse CN dumps into SQLite — store HELPFUL notes only (disk-conscious)."""
from __future__ import annotations

import csv
import logging
import sqlite3
from pathlib import Path

from backend.db import set_meta

log = logging.getLogger("desinfo.ingest.parse")

HELPFUL = "CURRENTLY_RATED_HELPFUL"
csv.field_size_limit(min(2**31 - 1, 10_000_000))


def _open_tsv(path: Path):
    return open(path, encoding="utf-8", newline="")


def load_helpful_ids(paths: list[Path]) -> set[str]:
    """Return set of note_ids with CURRENTLY_RATED_HELPFUL."""
    helpful: set[str] = set()
    scanned = 0
    for path in paths:
        log.info("reading status %s", path.name)
        with _open_tsv(path) as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                scanned += 1
                note_id = row.get("noteId") or row.get("note_id")
                if not note_id:
                    continue
                cur = row.get("currentStatus") or row.get("current_status") or ""
                if cur == HELPFUL:
                    helpful.add(note_id)
    log.info("status scanned=%s helpful=%s", scanned, len(helpful))
    return helpful


def upsert_notes(conn: sqlite3.Connection, note_paths: list[Path], helpful_ids: set[str]) -> int:
    """Insert/update HELPFUL notes only. Returns helpful notes upserted."""
    count = 0
    scanned = 0
    batch: list[tuple] = []

    def flush() -> None:
        nonlocal batch
        if not batch:
            return
        conn.executemany(
            """
            INSERT INTO notes(note_id, tweet_id, created_at_ms, summary, classification, current_status, is_helpful)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(note_id) DO UPDATE SET
                tweet_id=excluded.tweet_id,
                created_at_ms=excluded.created_at_ms,
                summary=excluded.summary,
                classification=excluded.classification,
                current_status=excluded.current_status,
                is_helpful=1
            """,
            batch,
        )
        batch = []

    for path in note_paths:
        log.info("reading notes %s (helpful filter)", path.name)
        with _open_tsv(path) as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                scanned += 1
                note_id = row.get("noteId") or row.get("note_id")
                if not note_id or note_id not in helpful_ids:
                    continue
                try:
                    created = int(row.get("createdAtMillis") or row.get("created_at_ms") or 0)
                except ValueError:
                    continue
                if created <= 0:
                    continue
                tweet_id = row.get("tweetId") or row.get("tweet_id") or ""
                summary = row.get("summary") or ""
                classification = row.get("classification") or ""
                batch.append((note_id, tweet_id, created, summary, classification, HELPFUL))
                count += 1
                if len(batch) >= 2000:
                    flush()
    flush()
    set_meta(conn, "notes_scanned", str(scanned))
    set_meta(conn, "notes_helpful", str(count))
    log.info("upserted %s helpful notes (scanned %s)", count, scanned)
    return count
