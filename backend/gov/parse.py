"""Parse X filter source for @handles + user ids (no X API)."""
from __future__ import annotations

import re
from typing import Any

# // @handle
# 14160928,
HANDLE_ID_RE = re.compile(
    r"//\s*@([A-Za-z0-9_]{1,15})\b[^\n]*\n\s*(\d{4,20})\s*,",
)

# Fallback: numeric ids in the LazyLock set, if a comment has no @handle.
BARE_ID_RE = re.compile(r"^\s*(\d{4,20})\s*,\s*$", re.MULTILINE)


def parse_handle_comment_user_ids(source: str) -> list[dict[str, str]]:
    """Extract unique accounts from a rust filter list with // @handle comments."""
    seen: set[str] = set()
    accounts: list[dict[str, str]] = []
    for handle, user_id in HANDLE_ID_RE.findall(source):
        key = user_id
        if key in seen:
            continue
        seen.add(key)
        accounts.append({"handle": handle, "user_id": user_id})
    return accounts


def parse_accounts(source: str, parser: str = "handle_comment_user_id") -> list[dict[str, str]]:
    if parser != "handle_comment_user_id":
        raise ValueError(f"Unknown gov parser: {parser}")
    return parse_handle_comment_user_ids(source)


def measure_from_filename(name: str) -> dict[str, Any]:
    """Generic metadata when a new *election_filter.rs appears in the repo."""
    stem = name.removesuffix(".rs")
    title = stem.replace("_", " ").strip()
    country_guess = stem.split("_")[0].replace("-", " ").title() if stem else "Pays inconnu"
    return {
        "id": stem,
        "country_code": "",
        "country": country_guess or "Pays inconnu",
        "authority": "Autorité non précisée dans le catalogue",
        "title": title,
        "effect": "Effet décrit dans le fichier source X",
        "effect_code": "unknown",
        "legal_basis": "",
        "source_path": f"home-mixer/filters/{name}",
        "announced_at": None,
        "parser": "handle_comment_user_id",
        "discovered": True,
    }
