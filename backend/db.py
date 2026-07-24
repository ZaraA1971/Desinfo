"""SQLite schema and helpers."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from backend.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    note_id TEXT PRIMARY KEY,
    tweet_id TEXT,
    created_at_ms INTEGER NOT NULL,
    summary TEXT,
    classification TEXT,
    current_status TEXT,
    is_helpful INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_notes_created ON notes(created_at_ms);
CREATE INDEX IF NOT EXISTS idx_notes_helpful ON notes(is_helpful, created_at_ms);

CREATE TABLE IF NOT EXISTS media (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    domains TEXT NOT NULL,
    x_handle TEXT
);

CREATE TABLE IF NOT EXISTS note_media (
    note_id TEXT NOT NULL,
    media_id TEXT NOT NULL,
    matched_domain TEXT,
    PRIMARY KEY (note_id, media_id),
    FOREIGN KEY (note_id) REFERENCES notes(note_id),
    FOREIGN KEY (media_id) REFERENCES media(id)
);

CREATE INDEX IF NOT EXISTS idx_note_media_media ON note_media(media_id);

CREATE TABLE IF NOT EXISTS note_theme (
    note_id TEXT PRIMARY KEY,
    theme TEXT NOT NULL,
    model TEXT,
    scored_at TEXT NOT NULL,
    FOREIGN KEY (note_id) REFERENCES notes(note_id)
);

CREATE INDEX IF NOT EXISTS idx_note_theme_theme ON note_theme(theme);

CREATE TABLE IF NOT EXISTS tweets (
    tweet_id TEXT PRIMARY KEY,
    text TEXT,
    lang TEXT,
    fetched_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ok'
);

CREATE TABLE IF NOT EXISTS media_posts_daily (
    media_id TEXT NOT NULL,
    day TEXT NOT NULL,
    post_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (media_id, day),
    FOREIGN KEY (media_id) REFERENCES media(id)
);

CREATE INDEX IF NOT EXISTS idx_media_posts_daily_day ON media_posts_daily(day);

CREATE TABLE IF NOT EXISTS media_post_windows (
    media_id TEXT NOT NULL,
    window_key TEXT NOT NULL,
    post_count INTEGER NOT NULL DEFAULT 0,
    synced_at TEXT NOT NULL,
    PRIMARY KEY (media_id, window_key),
    FOREIGN KEY (media_id) REFERENCES media(id)
);

CREATE TABLE IF NOT EXISTS politicians (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    party TEXT,
    x_handle TEXT
);

CREATE TABLE IF NOT EXISTS note_politician (
    note_id TEXT NOT NULL,
    politician_id TEXT NOT NULL,
    matched_alias TEXT,
    PRIMARY KEY (note_id, politician_id),
    FOREIGN KEY (note_id) REFERENCES notes(note_id),
    FOREIGN KEY (politician_id) REFERENCES politicians(id)
);

CREATE INDEX IF NOT EXISTS idx_note_politician_politician ON note_politician(politician_id);

CREATE TABLE IF NOT EXISTS politician_posts_daily (
    politician_id TEXT NOT NULL,
    day TEXT NOT NULL,
    post_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (politician_id, day),
    FOREIGN KEY (politician_id) REFERENCES politicians(id)
);

CREATE INDEX IF NOT EXISTS idx_politician_posts_daily_day ON politician_posts_daily(day);

CREATE TABLE IF NOT EXISTS politician_post_windows (
    politician_id TEXT NOT NULL,
    window_key TEXT NOT NULL,
    post_count INTEGER NOT NULL DEFAULT 0,
    synced_at TEXT NOT NULL,
    PRIMARY KEY (politician_id, window_key),
    FOREIGN KEY (politician_id) REFERENCES politicians(id)
);

CREATE TABLE IF NOT EXISTS ranking_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    window_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metric_mode TEXT NOT NULL,
    path TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingest_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    window_key TEXT NOT NULL,
    ip TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_exports_email ON exports(email);
CREATE INDEX IF NOT EXISTS idx_exports_created ON exports(created_at);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    settings = get_settings()
    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def db_session(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO ingest_meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM ingest_meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default
