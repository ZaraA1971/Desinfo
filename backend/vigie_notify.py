"""Pousse l'état Desinfo vers Vigie — succès comme échec, même enveloppe."""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("desinfo.vigie")

_HUB = "/srv/ops/incident-hub"
_HUB_ENV = Path(_HUB) / ".env"
_DAYS = (
    "lundi",
    "mardi",
    "mercredi",
    "jeudi",
    "vendredi",
    "samedi",
    "dimanche",
)
_MONTHS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


def next_x_sync_at(now: datetime | None = None) -> str:
    """Prochaine moisson : lundi 06:00 UTC (desinfo-x-sync.timer)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    days_ahead = (0 - now.weekday()) % 7
    candidate = (now + timedelta(days=days_ahead)).replace(
        hour=6, minute=0, second=0, microsecond=0
    )
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate.isoformat()


def _parse_dt(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _when_fr(value: Any) -> str:
    dt = _parse_dt(value)
    if dt is None:
        return "inconnu"
    return (
        f"{_DAYS[dt.weekday()]} {dt.day} {_MONTHS[dt.month - 1]} "
        f"{dt.strftime('%H:%M')}"
    )


def _window_fr(key: str) -> str:
    return str(key or "").replace("d", "j")


def _ready_windows(status: dict[str, Any] | None) -> list[str]:
    ready: list[str] = []
    for key, row in (status or {}).items():
        if isinstance(row, dict) and row.get("available"):
            ready.append(_window_fr(str(key)))
    return ready


def _top_names(path: Path, n: int = 2) -> list[str]:
    try:
        if not path.is_file():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    names: list[str] = []
    for row in data.get("items") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if name:
            names.append(name)
        if len(names) >= n:
            break
    return names


def _ensure_hub_token() -> None:
    if (os.getenv("INCIDENT_HUB_TOKEN") or os.getenv("VIGIE_INGRESS_TOKEN") or "").strip():
        return
    if not _HUB_ENV.is_file():
        return
    try:
        for line in _HUB_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("INCIDENT_HUB_TOKEN="):
                os.environ["INCIDENT_HUB_TOKEN"] = (
                    line.split("=", 1)[1].strip().strip('"').strip("'")
                )
                return
    except OSError:
        return


def brief_harvest(harvest: Any) -> dict[str, Any]:
    if not isinstance(harvest, dict):
        return {}
    sync = harvest.get("sync")
    if not isinstance(sync, dict):
        sync = {}
    cascade = harvest.get("cascade")
    if not isinstance(cascade, dict):
        cascade = {}
    return {
        "status": sync.get("status") or harvest.get("status"),
        "handles": sync.get("unique_handles"),
        "api_calls": sync.get("api_calls"),
        "skipped": sync.get("skipped_handles"),
        "errors": len(sync.get("errors") or []),
        "cascade": cascade.get("status"),
    }


def brief_ingest(ingest: Any) -> dict[str, Any]:
    if not isinstance(ingest, dict):
        return {}
    return {
        k: ingest[k]
        for k in (
            "status",
            "reason",
            "dump_date",
            "dump_days",
            "notes_upserted",
            "notes_touched",
            "last_ingest_at",
        )
        if k in ingest
    }


def brief_themes(themes: Any) -> dict[str, Any]:
    if themes == "skipped":
        return {"status": "skipped"}
    if not isinstance(themes, dict):
        return {}
    return {
        k: themes[k]
        for k in ("status", "reason", "classified", "pending_left", "window")
        if k in themes
    }


def brief_emails(emails: Any) -> dict[str, Any]:
    if not isinstance(emails, dict):
        return {}
    return {
        k: emails[k]
        for k in ("rows", "unique")
        if k in emails and emails[k] not in (None, "")
    }


def brief_gov(gov: Any) -> dict[str, Any]:
    if not isinstance(gov, dict):
        return {}
    return {
        k: gov[k]
        for k in ("measure_count", "account_count", "generated_at")
        if k in gov and gov[k] not in (None, "")
    }


def collect_picture() -> dict[str, Any]:
    """État actuel (même matière que /api/meta), sans e-mails ni secrets."""
    from backend.config import get_settings
    from backend.db import db_session, get_meta
    from backend.media_config import load_media_roster
    from backend.politicians.config import load_politicians_roster
    from backend.themes.classify import count_pending_themes
    from backend.windows.status import compute_windows_status

    settings = get_settings()
    roster = load_media_roster()
    politicians = load_politicians_roster()
    windows = compute_windows_status(kind="media")
    pol_windows = compute_windows_status(kind="politicians")
    snap_dir = settings.root / "data" / "snapshots"
    last_snapshot = None
    try:
        latest = snap_dir / "latest_7d.json"
        if latest.is_file():
            data = json.loads(latest.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                last_snapshot = data.get("generated_at")
    except (OSError, json.JSONDecodeError):
        last_snapshot = None

    last_ingest = last_theme = last_gov = last_x = last_x_status = None
    theme_classified = theme_pending = gov_measures = 0
    try:
        with db_session() as conn:
            last_ingest = get_meta(conn, "last_ingest_at")
            last_theme = get_meta(conn, "last_theme_classify_at")
            last_gov = get_meta(conn, "last_gov_sync_at")
            last_x = get_meta(conn, "last_x_sync_at")
            last_x_status = get_meta(conn, "last_x_sync_status")
            gov_measures = int(get_meta(conn, "gov_measure_count") or 0)
            theme_classified = int(
                conn.execute("SELECT COUNT(*) AS n FROM note_theme").fetchone()["n"]
            )
            theme_pending = count_pending_themes(window_key="7d")
    except Exception:
        log.exception("desinfo vigie meta")

    return {
        "last_ingest_at": last_ingest,
        "last_snapshot_at": last_snapshot,
        "last_theme_classify_at": last_theme,
        "last_gov_sync_at": last_gov,
        "last_x_sync_at": last_x,
        "last_x_sync_status": last_x_status,
        "theme_classified": theme_classified,
        "theme_pending": theme_pending,
        "gov_measure_count": gov_measures,
        "roster_size": len(roster.get("media") or []),
        "politicians_roster_size": len(politicians.get("candidates") or []),
        "windows_ready": _ready_windows(windows),
        "politicians_windows_ready": _ready_windows(pol_windows),
        "next_x_sync_at": next_x_sync_at(),
        "top_media": _top_names(snap_dir / "latest_7d.json"),
        "top_politicians": _top_names(snap_dir / "latest_politicians_7d.json"),
    }


def build_weekly_payload(run: dict[str, Any] | None = None) -> dict[str, Any]:
    run = dict(run or {})
    picture = run.get("picture") if isinstance(run.get("picture"), dict) else {}
    failed = str(run.get("status") or "") in ("failed", "error")
    ingest = brief_ingest(run.get("ingest"))
    themes = brief_themes(run.get("themes"))
    harvest = brief_harvest(run.get("harvest"))
    emails = brief_emails(run.get("emails"))
    gov = brief_gov(run.get("gov"))
    reason = str(run.get("reason") or ingest.get("reason") or "").strip()

    title = (
        "Desinfo — sync hebdo en échec" if failed else "Desinfo — sync hebdo à jour"
    )

    lines: list[str] = []
    if ingest:
        status = ingest.get("status") or "?"
        if status == "skipped":
            bit = "rien de nouveau"
        elif status == "ok":
            notes = ingest.get("notes_upserted")
            bit = f"notes mises à jour : {notes}" if notes not in (None, "") else "fait"
        else:
            bit = str(status)
        dump = ingest.get("dump_date")
        if dump:
            bit += f" (dernier jour {dump})"
        lines.append(f"Ingest : {bit}.")
    elif picture.get("last_ingest_at"):
        lines.append(f"Ingest : {_when_fr(picture.get('last_ingest_at'))}.")

    if themes:
        if themes.get("status") == "skipped":
            lines.append("Thèmes : passés.")
        else:
            classified = themes.get("classified")
            pending = themes.get("pending_left")
            if pending is None:
                pending = picture.get("theme_pending")
            lines.append(
                f"Thèmes : {classified if classified is not None else '?'} classés cette fois, "
                f"{pending if pending is not None else '?'} encore en attente."
            )
    elif picture.get("theme_classified") is not None:
        lines.append(
            f"Thèmes : {picture.get('theme_classified')} classés au total, "
            f"{picture.get('theme_pending')} en attente."
        )

    if harvest:
        st = harvest.get("status") or "fait"
        if harvest.get("handles") is not None:
            st += f" — {harvest.get('handles')} comptes"
        if harvest.get("skipped") not in (None, 0):
            st += f", {harvest.get('skipped')} déjà à jour"
        if harvest.get("api_calls") not in (None, ""):
            st += f", {harvest.get('api_calls')} appels"
        if harvest.get("errors"):
            st += f", {harvest.get('errors')} erreur(s)"
        lines.append(f"Réseaux : {st}.")
    elif picture.get("last_x_sync_at"):
        lines.append(
            f"Réseaux : {picture.get('last_x_sync_status') or 'fait'} "
            f"({_when_fr(picture.get('last_x_sync_at'))})."
        )

    media_w = picture.get("windows_ready") or []
    pol_w = picture.get("politicians_windows_ready") or []
    snaps = run.get("snapshots") or []
    if snaps and not isinstance(snaps, list):
        snaps = []
    if media_w or pol_w:
        lines.append(
            "Fenêtres : médias "
            f"{', '.join(media_w) or '—'} ; candidats "
            f"{', '.join(pol_w) or '—'}."
        )
    elif snaps:
        lines.append("Classements écrits : " + ", ".join(str(x) for x in snaps) + ".")

    roster = picture.get("roster_size")
    pols = picture.get("politicians_roster_size")
    if roster not in (None, "") or pols not in (None, ""):
        lines.append(
            f"Suivi : {roster if roster is not None else '?'} médias, "
            f"{pols if pols is not None else '?'} candidats."
        )

    if gov.get("measure_count") not in (None, "") or picture.get("gov_measure_count"):
        n = gov.get("measure_count", picture.get("gov_measure_count"))
        lines.append(f"Demandes des États : {n} mesure(s).")

    tops = []
    if picture.get("top_media"):
        tops.append("médias " + ", ".join(picture["top_media"]))
    if picture.get("top_politicians"):
        tops.append("candidats " + ", ".join(picture["top_politicians"]))
    if tops:
        lines.append("Tête 7 j : " + " ; ".join(tops) + ".")

    nxt = picture.get("next_x_sync_at") or next_x_sync_at()
    lines.append(f"Prochaine moisson : {_when_fr(nxt)}.")
    if reason and failed:
        lines.append(f"Raison : {reason[:400]}.")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M")
    status = "failed" if failed else "ok"
    facts: dict[str, Any] = {
        "date": datetime.now(timezone.utc).isoformat(),
        "actor": "desinfo",
        "status": status,
        "id": f"weekly-{stamp}",
        "link": "https://desinfo.electronlibre.info",
        "theme": "sync",
        "label": "hebdo",
        "next_x_sync_at": nxt,
        "roster_size": roster,
        "politicians_roster_size": pols,
        "windows_ready": media_w,
        "theme_pending": picture.get("theme_pending"),
    }
    if ingest.get("status"):
        facts["ingest"] = ingest.get("status")
    if harvest.get("status"):
        facts["x_sync"] = harvest.get("status")
    if reason:
        facts["reason"] = reason[:400]

    return {
        "title": title,
        "body": " ".join(lines)[:6000],
        "kind": "alert" if failed else "watch",
        "facts": facts,
        "fingerprint": f"desinfo:weekly:{stamp}:{status}"[:200],
    }


def push_weekly(run: dict[str, Any] | None = None) -> dict[str, Any]:
    run = dict(run or {})
    if "picture" not in run:
        try:
            run["picture"] = collect_picture()
        except Exception:
            log.exception("desinfo vigie picture")
            run["picture"] = {}
    payload = build_weekly_payload(run)
    try:
        if _HUB not in sys.path:
            sys.path.insert(0, _HUB)
        _ensure_hub_token()
        import vigie_door

        out = vigie_door.post_ingress(
            source="desinfo",
            kind=payload["kind"],
            title=payload["title"],
            body=payload["body"],
            facts=vigie_door.door_facts(**payload["facts"]),
            fingerprint=payload["fingerprint"],
            timeout=45,
        )
        if not out.get("ok"):
            log.warning("desinfo vigie refusée: %s", out.get("error"))
        return out
    except Exception as exc:
        log.exception("desinfo vigie")
        return {"ok": False, "error": str(exc)[:200]}
