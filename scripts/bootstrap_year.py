#!/usr/bin/env python3
"""Bootstrap media_roster.yml from 365d CN attribution."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.config import get_settings
from backend.ingest.pipeline import run_ingest
from backend.scoring.bootstrap import bootstrap_roster
from backend.scoring.rank import score_all_windows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--days", type=int, default=None)
    parser.add_argument("--min-cn", type=int, default=None)
    args = parser.parse_args()

    settings = get_settings()
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if not args.skip_ingest:
        run_ingest(skip_download=args.skip_download)

    roster = bootstrap_roster(days=args.days, min_cn=args.min_cn)
    print(json.dumps({"roster_size": len(roster["media"]), "generated_at": roster["generated_at"]}, indent=2))
    score_all_windows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
