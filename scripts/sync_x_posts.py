#!/usr/bin/env python3
"""Manual X sync helper — prefer weekly timer / run_weekly.py."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.config import get_settings
from backend.db import init_db
from backend.politicians.rank import score_all_politicians_windows
from backend.scoring.rank import score_all_windows
from backend.x_client.client import XApiNotConfigured
from backend.x_client.sync import (
    cascade_longer_windows,
    cascade_politician_windows,
    run_weekly_harvest,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync X 7d counts (+ cascade). Prefer scripts/run_weekly.py"
    )
    parser.add_argument("--windows", nargs="*", default=None, help="Défaut: 7d only")
    parser.add_argument(
        "--all-windows",
        action="store_true",
        help="Ignoré pour l'API (7d only) — cascade calcule 30/90/365",
    )
    parser.add_argument("--cascade-only", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    init_db()

    if args.cascade_only:
        cascade = {
            "cascade": cascade_longer_windows(),
            "politicians_cascade": cascade_politician_windows(),
        }
        print(json.dumps(cascade, indent=2, ensure_ascii=False))
        paths = score_all_windows() + score_all_politicians_windows()
        print("snapshots:", [str(p) for p in paths])
        return 0

    if not settings.x_api_configured:
        print("ERROR: X API non configurée (.env X_BEARER_TOKEN)", file=sys.stderr)
        return 2

    if args.windows and any(w != "7d" for w in args.windows):
        logging.warning("--windows: API reste 7d ; cascade pour le reste")
    if args.all_windows:
        logging.warning("--all-windows: API reste 7d ; cascade pour le reste")

    try:
        result = run_weekly_harvest()
    except XApiNotConfigured as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    print(json.dumps(result, indent=2, ensure_ascii=False))
    paths = score_all_windows() + score_all_politicians_windows()
    print("snapshots:", [str(p) for p in paths])

    if (result.get("sync") or {}).get("status") == "partial_credits_depleted":
        print(
            "WARNING: sync partiel — crédits X épuisés. "
            "Recharge puis relance (reprise auto des comptes manquants).",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
