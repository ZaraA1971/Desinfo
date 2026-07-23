"""Load media domain registry and roster YAML."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from backend.config import get_settings


def load_media_domains(path: Path | None = None) -> list[dict[str, Any]]:
    settings = get_settings()
    p = path or settings.media_domains_path
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    media = data.get("media") or []
    if not isinstance(media, list):
        raise ValueError(f"Invalid media_domains.yml: expected list under 'media' in {p}")
    return media


def load_media_roster(path: Path | None = None) -> dict[str, Any]:
    settings = get_settings()
    p = path or settings.media_roster_path
    if not p.exists():
        return {"generated_at": None, "window_days": settings.bootstrap_days, "media": []}
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


def save_media_roster(roster: dict[str, Any], path: Path | None = None) -> None:
    settings = get_settings()
    p = path or settings.media_roster_path
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".yml.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(roster, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    tmp.replace(p)


def build_domain_index(media_list: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map lowercase domain → media dict (longest domain wins on ties via explicit order)."""
    index: dict[str, dict[str, Any]] = {}
    for m in media_list:
        for d in m.get("domains") or []:
            dom = str(d).lower().strip().lstrip(".")
            if not dom:
                continue
            # Prefer longer / more specific domains if already present
            existing = index.get(dom)
            if existing is None:
                index[dom] = m
            else:
                # keep first unless new is more specific (shouldn't share exact key)
                pass
    return index
