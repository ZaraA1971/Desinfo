#!/usr/bin/env python3
"""Classify attributed notes into themes (LLM) then refresh media snapshots."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.config import get_settings
from backend.db import init_db
from backend.scoring.rank import score_all_windows
from backend.themes.classify import classify_pending_notes


def main() -> int:
    parser = argparse.ArgumentParser(description="desinfo theme classify + rescore")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max notes this run (default DESINFO_THEME_MAX_PER_RUN)",
    )
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reclassify already-tagged notes (prompt upgrade)",
    )
    parser.add_argument("--skip-score", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    init_db()
    res = classify_pending_notes(
        limit=args.limit, batch_size=args.batch_size, force=args.force
    )
    print("themes:", res)
    if not args.skip_score:
        paths = score_all_windows()
        print("snapshots:", [str(p) for p in paths])
    return 0 if res.get("status") in ("ok", "partial", "skipped") else 1


if __name__ == "__main__":
    raise SystemExit(main())
