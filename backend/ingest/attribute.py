"""Attribute HELPFUL notes to French media via URL domains in note text."""
from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any
from urllib.parse import urlparse

from backend.media_config import build_domain_index, load_media_domains

log = logging.getLogger("desinfo.ingest.attribute")

URL_RE = re.compile(
    r"https?://[^\s\]\)\"\'<>]+",
    re.IGNORECASE,
)


def extract_domains(text: str) -> list[str]:
    domains: list[str] = []
    for match in URL_RE.findall(text or ""):
        url = match.rstrip(".,;:!?)]}'\"")
        try:
            host = urlparse(url).hostname or ""
        except Exception:
            continue
        host = host.lower().removeprefix("www.")
        if host:
            domains.append(host)
    return domains


def match_media(domains: list[str], index: dict[str, dict[str, Any]]) -> list[tuple[str, str]]:
    """Return list of (media_id, matched_domain). Longest suffix match wins per domain."""
    found: dict[str, str] = {}
    # Sort registry keys by length desc for suffix matching
    keys = sorted(index.keys(), key=len, reverse=True)
    for host in domains:
        for key in keys:
            if host == key or host.endswith("." + key):
                mid = index[key]["id"]
                if mid not in found:
                    found[mid] = key
                break
    return list(found.items())


def sync_media_table(conn: sqlite3.Connection, media_list: list[dict[str, Any]]) -> None:
    for m in media_list:
        domains = ",".join(m.get("domains") or [])
        conn.execute(
            """
            INSERT INTO media(id, name, domains, x_handle)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                domains=excluded.domains,
                x_handle=excluded.x_handle
            """,
            (m["id"], m["name"], domains, m.get("x_handle")),
        )


def attribute_notes(conn: sqlite3.Connection) -> int:
    media_list = load_media_domains()
    sync_media_table(conn, media_list)
    index = build_domain_index(media_list)
    if not index:
        raise RuntimeError("Empty media domain index — check config/media_domains.yml")

    conn.execute("DELETE FROM note_media")
    rows = conn.execute(
        "SELECT note_id, summary FROM notes WHERE is_helpful=1"
    ).fetchall()

    links = 0
    batch: list[tuple] = []
    for row in rows:
        domains = extract_domains(row["summary"] or "")
        matches = match_media(domains, index)
        for media_id, matched in matches:
            batch.append((row["note_id"], media_id, matched))
            links += 1
        if len(batch) >= 2000:
            conn.executemany(
                "INSERT OR IGNORE INTO note_media(note_id, media_id, matched_domain) VALUES (?,?,?)",
                batch,
            )
            batch = []
    if batch:
        conn.executemany(
            "INSERT OR IGNORE INTO note_media(note_id, media_id, matched_domain) VALUES (?,?,?)",
            batch,
        )
    log.info("attributed %s note↔media links from %s helpful notes", links, len(rows))
    return links
