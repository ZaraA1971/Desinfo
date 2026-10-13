"""Catalogue des mesures d'État déjà identifiées dans x-algorithm."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from backend.config import get_settings

DISCOVER_SUFFIXES = (
    "_election_filter.rs",
    "_government_filter.rs",
    "_legal_filter.rs",
    "_takedown_filter.rs",
)


def catalog_path() -> Path:
    return get_settings().root / "config" / "gov_measures.yml"


def load_gov_catalog() -> dict[str, Any]:
    path = catalog_path()
    if not path.exists():
        raise FileNotFoundError(f"Catalogue manquant : {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("gov_measures.yml must be a mapping")
    measures = data.get("measures") or []
    if not isinstance(measures, list):
        raise ValueError("gov_measures.yml measures must be a list")
    return data


def cataloged_source_paths(catalog: dict[str, Any] | None = None) -> set[str]:
    data = catalog or load_gov_catalog()
    return {
        str(m.get("source_path") or "").strip()
        for m in (data.get("measures") or [])
        if m.get("source_path")
    }


def is_discoverable_filter(name: str) -> bool:
    lower = name.lower()
    return any(lower.endswith(suf) for suf in DISCOVER_SUFFIXES)
