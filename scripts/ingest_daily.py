#!/usr/bin/env python3
"""Daily CN ingest + score (+ emails CSV). X sync is weekly — see sync_x_weekly.py."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.config import get_settings
from backend.ingest.pipeline import run_ingest
from backend.politicians.rank import score_all_politicians_windows
from backend.scoring.bootstrap import bootstrap_roster
from backend.scoring.rank import score_all_windows
from backend.x_client.sync import cascade_longer_windows, cascade_politician_windows


def main() -> int:
    parser = argparse.ArgumentParser(description="desinfo daily ingest")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--bootstrap", action="store_true", help="Rebuild media_roster.yml")
    parser.add_argument(
        "--with-x-sync",
        action="store_true",
        help="Exceptionnel: sync X 7d aujourd'hui (sinon timer hebdo)",
    )
    parser.add_argument("--windows", nargs="*", default=None)
    args = parser.parse_args()

    settings = get_settings()
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    result = run_ingest(skip_download=args.skip_download)
    print("ingest:", result)

    roster = load_or_bootstrap(args.bootstrap)
    print("roster_size:", len(roster.get("media") or []))

    if args.with_x_sync and settings.x_api_configured:
        from backend.x_client.sync import sync_roster_post_counts

        xres = sync_roster_post_counts(windows=["7d"])
        print("x_sync:", xres)

    # Cheap: refresh longer windows if daily history already allows it
    cres = cascade_longer_windows()
    print("cascade:", cres)
    pcres = cascade_politician_windows()
    print("politicians_cascade:", pcres)

    paths = score_all_windows(args.windows)
    print("snapshots:", [str(p) for p in paths])
    politician_paths = score_all_politicians_windows(args.windows)
    print("politicians_snapshots:", [str(p) for p in politician_paths])

    from backend.export.emails_csv import write_emails_csv

    csv_res = write_emails_csv()
    print("emails_csv:", csv_res)
    return 0


def load_or_bootstrap(force: bool):
    from backend.media_config import load_media_roster

    roster = load_media_roster()
    if force or not roster.get("media"):
        return bootstrap_roster()
    return roster


if __name__ == "__main__":
    raise SystemExit(main())
