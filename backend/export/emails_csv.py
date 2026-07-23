"""Admin CSV dump of collected export emails."""
from __future__ import annotations

import csv
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.config import get_settings
from backend.db import db_session

log = logging.getLogger("desinfo.export_emails")


def write_emails_csv(*, when: datetime | None = None) -> dict[str, Any]:
    """
    Write collected export emails to data/ for admin.
    - exports_emails_latest.csv (full history)
    - exports_emails_YYYYMMDD.csv (dated snapshot)
    """
    settings = get_settings()
    when = when or datetime.now(timezone.utc)
    day = when.strftime("%Y%m%d")
    out_dir = settings.root / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    latest = out_dir / "exports_emails_latest.csv"
    dated = out_dir / f"exports_emails_{day}.csv"

    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT created_at, email, window_key, ip
            FROM exports
            ORDER BY id ASC
            """
        ).fetchall()

    fieldnames = ["created_at", "email", "window_key", "ip"]
    payload = [dict(r) for r in rows]

    for path in (latest, dated):
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(payload)
        tmp.replace(path)
        os.chmod(path, 0o600)

    # Unique emails (first seen)
    unique_path = out_dir / "exports_emails_unique_latest.csv"
    seen: set[str] = set()
    unique_rows: list[dict[str, str]] = []
    for r in payload:
        email = (r.get("email") or "").strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        unique_rows.append(
            {
                "email": email,
                "first_seen": r.get("created_at") or "",
                "window_key": r.get("window_key") or "",
            }
        )
    tmp = unique_path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["email", "first_seen", "window_key"])
        w.writeheader()
        w.writerows(unique_rows)
    tmp.replace(unique_path)
    os.chmod(unique_path, 0o600)

    result = {
        "rows": len(payload),
        "unique": len(unique_rows),
        "latest": str(latest),
        "dated": str(dated),
        "unique_file": str(unique_path),
    }
    log.info("emails csv written: %s", result)
    return result
