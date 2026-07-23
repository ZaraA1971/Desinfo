"""Load politicians roster YAML (mirrors backend/media_config.py)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from backend.config import get_settings


def load_politicians_roster(path: Path | None = None) -> dict[str, Any]:
    """Return roster dict with a `candidates` list (id, name, party, x_handle, aliases[])."""
    settings = get_settings()
    p = path or settings.politicians_roster_path
    if not p.exists():
        return {"election": None, "source": None, "updated_at": None, "candidates": []}
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    candidates = data.get("candidates") or []
    if not isinstance(candidates, list):
        raise ValueError(
            f"Invalid politicians_roster.yml: expected list under 'candidates' in {p}"
        )
    data["candidates"] = candidates
    return data
