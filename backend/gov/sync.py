"""Download X public filters → parse → snapshot. No X API."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from backend.config import get_settings
from backend.db import db_session, set_meta
from backend.gov.catalog import (
    cataloged_source_paths,
    is_discoverable_filter,
    load_gov_catalog,
)
from backend.gov.parse import measure_from_filename, parse_accounts

log = logging.getLogger("desinfo.gov")

USER_AGENT = "desinfo-electronlibre/gov-sync (+https://desinfo.electronlibre.info)"
TIMEOUT = httpx.Timeout(45.0)
DISCLAIMER = (
    "On montre seulement ce que X a mis dans son code public. "
    "Ce n'est pas la liste de tous les posts retirés à la demande d'un État."
)


def snapshot_path() -> Path:
    return get_settings().snapshots_dir / "latest_gov.json"


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/plain"},
        follow_redirects=True,
    )


def _raw_url(raw_base: str, source_path: str) -> str:
    return f"{raw_base.rstrip('/')}/{source_path.lstrip('/')}"


def _blob_url(blob_base: str, source_path: str) -> str:
    return f"{blob_base.rstrip('/')}/{source_path.lstrip('/')}"


def fetch_text(client: httpx.Client, url: str) -> str:
    resp = client.get(url)
    if resp.status_code != 200:
        raise RuntimeError(f"Téléchargement échoué {resp.status_code} {url}")
    return resp.text


def list_filter_files(client: httpx.Client, filters_api: str) -> list[dict[str, Any]]:
    resp = client.get(filters_api)
    if resp.status_code != 200:
        raise RuntimeError(f"Liste des filtres X échouée {resp.status_code}")
    data = resp.json()
    if not isinstance(data, list):
        raise RuntimeError("Réponse GitHub inattendue pour home-mixer/filters")
    return [item for item in data if item.get("type") == "file" and item.get("name")]


def _build_measure(
    spec: dict[str, Any],
    source: str,
    *,
    raw_base: str,
    blob_base: str,
    discovered: bool,
) -> dict[str, Any]:
    parser = str(spec.get("parser") or "handle_comment_user_id")
    accounts = parse_accounts(source, parser)
    source_path = str(spec.get("source_path") or "")
    return {
        "id": spec.get("id"),
        "country_code": spec.get("country_code") or "",
        "country": spec.get("country") or "Pays inconnu",
        "authority": spec.get("authority") or "",
        "title": spec.get("title") or spec.get("id"),
        "effect": spec.get("effect") or "",
        "effect_code": spec.get("effect_code") or "",
        "legal_basis": spec.get("legal_basis") or "",
        "announced_at": spec.get("announced_at"),
        "source_path": source_path,
        "source_url": _blob_url(blob_base, source_path),
        "raw_url": _raw_url(raw_base, source_path),
        "account_count": len(accounts),
        "discovered": discovered,
        "accounts": accounts,
    }


def write_gov_snapshot(snapshot: dict[str, Any]) -> Path:
    settings = get_settings()
    settings.snapshots_dir.mkdir(parents=True, exist_ok=True)
    path = snapshot_path()
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)
    with db_session() as conn:
        set_meta(conn, "last_gov_sync_at", snapshot["generated_at"])
        set_meta(conn, "gov_measure_count", str(snapshot.get("measure_count") or 0))
        set_meta(conn, "gov_account_count", str(snapshot.get("account_count") or 0))
    log.info(
        "wrote gov snapshot measures=%s accounts=%s",
        snapshot.get("measure_count"),
        snapshot.get("account_count"),
    )
    return path


def sync_gov_measures() -> dict[str, Any]:
    catalog = load_gov_catalog()
    raw_base = str(catalog.get("raw_base") or "").rstrip("/")
    blob_base = str(catalog.get("blob_base") or "").rstrip("/")
    filters_api = str(catalog.get("filters_api") or "")
    source_repo = str(catalog.get("source_repo") or "")
    if not raw_base or not blob_base:
        raise ValueError("gov_measures.yml: raw_base et blob_base requis")

    known_paths = cataloged_source_paths(catalog)
    measures: list[dict[str, Any]] = []

    with _client() as client:
        for spec in catalog.get("measures") or []:
            source_path = str(spec.get("source_path") or "")
            if not source_path:
                raise ValueError(f"Mesure sans source_path: {spec.get('id')}")
            source = fetch_text(client, _raw_url(raw_base, source_path))
            measures.append(
                _build_measure(
                    spec,
                    source,
                    raw_base=raw_base,
                    blob_base=blob_base,
                    discovered=False,
                )
            )

        discovered_names: list[str] = []
        if filters_api:
            try:
                listed = list_filter_files(client, filters_api)
            except Exception as e:
                log.warning("découverte des filtres X impossible: %s", e)
                listed = []
            for item in listed:
                name = str(item.get("name") or "")
                path = f"home-mixer/filters/{name}"
                if not is_discoverable_filter(name) or path in known_paths:
                    continue
                source = fetch_text(client, _raw_url(raw_base, path))
                spec = measure_from_filename(name)
                measures.append(
                    _build_measure(
                        spec,
                        source,
                        raw_base=raw_base,
                        blob_base=blob_base,
                        discovered=True,
                    )
                )
                discovered_names.append(name)

    if not measures:
        raise RuntimeError("Aucune mesure d'État extraite du code X")

    now = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "kind": "gov",
        "generated_at": now,
        "source_repo": source_repo,
        "disclaimer": DISCLAIMER,
        "measure_count": len(measures),
        "account_count": sum(int(m.get("account_count") or 0) for m in measures),
        "discovered_files": discovered_names,
        "measures": measures,
    }
    path = write_gov_snapshot(snapshot)
    return {
        "path": str(path),
        "measure_count": snapshot["measure_count"],
        "account_count": snapshot["account_count"],
        "discovered_files": discovered_names,
        "generated_at": now,
    }
