#!/usr/bin/env python3
"""Backward-compatible alias — prefer scripts/run_weekly.py (systemd timer)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_weekly import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
