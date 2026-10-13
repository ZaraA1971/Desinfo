#!/usr/bin/env python3
"""Moisson des demandes d'États publiées dans le code X (x-algorithm)."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.config import get_settings
from backend.db import init_db
from backend.gov.sync import sync_gov_measures


def main() -> int:
    settings = get_settings()
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    init_db()
    result = sync_gov_measures()
    print("gov:", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
