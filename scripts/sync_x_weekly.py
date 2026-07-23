#!/usr/bin/env python3
"""Weekly X harvest: 7d counts/recent + cascade 30/90/365 from daily store + score."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.config import get_settings
from backend.db import init_db
from backend.politicians.rank import score_all_politicians_windows
from backend.scoring.rank import score_all_windows
from backend.x_client.sync import (
    cascade_longer_windows,
    cascade_politician_windows,
    run_weekly_harvest,
    sync_roster_post_counts,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="desinfo weekly X 7d harvest + cascade")
    parser.add_argument(
        "--cascade-only",
        action="store_true",
        help="Skip X API; only recompute longer windows from media_posts_daily",
    )
    parser.add_argument("--skip-score", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    init_db()

    if not settings.x_api_configured and not args.cascade_only:
        logging.error("X_BEARER_TOKEN manquant — utilisez --cascade-only si besoin")
        return 2

    if args.cascade_only:
        result = {
            "sync": None,
            "cascade": cascade_longer_windows(),
            "politicians_sync": None,
            "politicians_cascade": cascade_politician_windows(),
        }
    else:
        result = run_weekly_harvest()
    print("harvest:", result)

    if not args.skip_score:
        paths = score_all_windows()
        print("snapshots:", [str(p) for p in paths])
        politician_paths = score_all_politicians_windows()
        print("politicians_snapshots:", [str(p) for p in politician_paths])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
