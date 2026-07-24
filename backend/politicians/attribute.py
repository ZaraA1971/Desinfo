"""Attribute HELPFUL notes to declared politicians via @handle mention or name alias.

Mirrors backend/ingest/attribute.py (media, URL-domain based) but matches on note
summary text against each candidate's @handle and name aliases. Does NOT touch
note_media — media and politicians attribution are independent pipelines.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

from backend.politicians.config import load_politicians_roster

log = logging.getLogger("desinfo.politicians.attribute")


def sync_politicians_table(conn: sqlite3.Connection, candidates: list[dict[str, Any]]) -> None:
    for c in candidates:
        conn.execute(
            """
            INSERT INTO politicians(id, name, party, x_handle)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                party=excluded.party,
                x_handle=excluded.x_handle
            """,
            (c["id"], c["name"], c.get("party"), c.get("x_handle")),
        )


def _match_terms(candidate: dict[str, Any]) -> list[str]:
    """Alias + @handle terms for a candidate, sorted longest-first.

    Longest-first ensures a full name is preferred as the recorded matched_alias
    when several aliases of the same candidate are present, while still falling
    back to short aliases (e.g. "Mélenchon") when that's all the note contains.
    """
    terms: list[str] = [str(a) for a in (candidate.get("aliases") or []) if a]
    handle = candidate.get("x_handle")
    if handle:
        at_handle = f"@{str(handle).lstrip('@')}"
        if at_handle.lower() not in (t.lower() for t in terms):
            terms.append(at_handle)
    terms = [t.strip() for t in terms if t and t.strip()]
    terms.sort(key=len, reverse=True)
    return terms


def attribute_politicians(
    conn: sqlite3.Connection,
    *,
    note_ids: set[str] | None = None,
    rebuild: bool = False,
) -> int:
    """
    Attribute notes to politicians. Incremental by default (note_ids from latest dump).
    rebuild=True only when roster config changes (full re-link).
    """
    roster = load_politicians_roster()
    candidates = roster.get("candidates") or []
    sync_politicians_table(conn, candidates)

    if rebuild:
        conn.execute("DELETE FROM note_politician")
        log.info("politician attribution rebuild")
    elif note_ids:
        if not note_ids:
            log.info("politician attribution incremental — 0 notes")
            return 0
        placeholders = ",".join("?" * len(note_ids))
        conn.execute(
            f"DELETE FROM note_politician WHERE note_id IN ({placeholders})",
            list(note_ids),
        )
        log.info("politician attribution incremental — %s notes", len(note_ids))
    else:
        log.info("politician attribution backfill unlinked")

    if not candidates:
        log.warning("empty politicians roster — no attribution performed")
        return 0

    candidate_terms = [
        (c["id"], _match_terms(c)) for c in candidates if c.get("id")
    ]

    if rebuild:
        rows = conn.execute(
            "SELECT note_id, summary FROM notes WHERE is_helpful=1"
        ).fetchall()
    elif note_ids:
        placeholders = ",".join("?" * len(note_ids))
        rows = conn.execute(
            f"""
            SELECT note_id, summary FROM notes
            WHERE is_helpful=1 AND note_id IN ({placeholders})
            """,
            list(note_ids),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT n.note_id, n.summary FROM notes n
            WHERE n.is_helpful=1
              AND NOT EXISTS (
                SELECT 1 FROM note_politician np WHERE np.note_id = n.note_id
              )
            """
        ).fetchall()

    links = 0
    batch: list[tuple] = []
    for row in rows:
        summary = row["summary"] or ""
        if not summary:
            continue
        summary_lower = summary.lower()
        for politician_id, terms in candidate_terms:
            matched_alias = None
            for term in terms:
                if term.lower() in summary_lower:
                    matched_alias = term
                    break
            if matched_alias:
                batch.append((row["note_id"], politician_id, matched_alias))
                links += 1
        if len(batch) >= 2000:
            conn.executemany(
                "INSERT OR IGNORE INTO note_politician(note_id, politician_id, matched_alias) "
                "VALUES (?,?,?)",
                batch,
            )
            batch = []
    if batch:
        conn.executemany(
            "INSERT OR IGNORE INTO note_politician(note_id, politician_id, matched_alias) "
            "VALUES (?,?,?)",
            batch,
        )
    log.info(
        "attributed %s note↔politician links from %s helpful notes", links, len(rows)
    )
    return links
