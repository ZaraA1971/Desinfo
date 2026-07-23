"""Classify attributed HELPFUL notes into thematic buckets via small LLM."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from backend.config import get_settings
from backend.db import db_session, set_meta
from backend.themes.openai_chat import post_chat_completion
from backend.themes.taxonomy import ALL_THEMES, RADAR_THEMES, normalize_theme

log = logging.getLogger("desinfo.themes.classify")

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)

SYSTEM_PROMPT = f"""Tu classes des Community Notes (X) en UNE thématique dominante.
Thèmes autorisés (ids exacts uniquement) :
{", ".join(ALL_THEMES)}

Règle d’or : classe selon le SUJET corrigé par la note (ce que le post affirmait de faux), pas selon le média cité ni la langue.

Définitions :
- politique : vie politique (surtout FR) — partis, élections, gouvernement, parlement, personnalités politiques, sondages, discours partisans. Si le sujet est un politicien FR/UE et sa position (même sur l’Ukraine/Europe), préfère politique.
- sante : santé publique, médecine, vaccins, hôpitaux, épidémies, médicaments, nutrition médicale. PAS un simple fait divers avec blessé si le cœur n’est pas médical.
- economie : entreprises, marchés, finance, inflation, budget, emploi, commerce, IPO, banques centrales.
- justice : procédures judiciaires, tribunaux, police judiciaire, peines, enquêtes criminelles formelles, procès. Un crime « fait divers » sans angle judiciaire → faits_divers.
- international : géopolitique, guerres, diplomatie, États étrangers, conflits, OTAN, sans que le cœur soit une polémique partisane FR.
- science : recherche scientifique, climat/environnement scientifique, espace/NASA, études, physique, biologie. Chemtrails / pseudo-science → science.
- technologie : produits numériques, IA générative, plateformes tech, cybersécurité, deepfakes techniques, bugs. Un conflit géopolitique qui mentionne Google/IA → international (sauf si la note corrige un point purement technique/IA).
- faits_divers : accidents, incendies, crimes isolés, sport/divertissement, images trompeuses de scènes locales sans enjeu politique. JAMAIS pour guerre, diplomatie, pétrole/sanctions d’État, élections.
- autre : meta-média (« déjà traité à l’antenne »), humour TV, rumeurs sans thème clair, sport institutionnel (FIFA) sans autre angle, ou vraiment hors axes.

Priorité en cas d’ambiguïté (du plus prioritaire) :
1) Si une personnalité / un parti politique FR (ou candidat) est le sujet principal de la note → politique — même si le contenu porte sur l’Ukraine, l’Europe, la Crimée, etc.
2) international si conflit / État / diplomatie au centre (sans personnalité FR comme sujet)
3) justice si procès / peine / enquête judiciaire au centre
4) sinon le thème le plus spécifique parmi les autres
5) autre en dernier recours

Exemples :
- « Marine Le Pen a nié l’annexion de la Crimée » → politique
- « Attaque dans le détroit d’Ormuz » → international
- « Vidéo d’incendie de marché sans lien avec une guerre » → faits_divers
- « Image générée par IA d’un animal » → technologie
- « Manifestation contre les contrats Google/Israël » → international

Réponds UNIQUEMENT un JSON array valide :
[{{"id":"<note_id>","theme":"<id>"}}]
Pas de markdown, pas de commentaire, un seul thème par id."""


def _extract_json(text: str) -> Any:
    raw = text.strip()
    m = _JSON_FENCE.search(raw)
    if m:
        raw = m.group(1).strip()
    return json.loads(raw)


def pending_attributed_notes(limit: int, *, force: bool = False) -> list[dict[str, str]]:
    """HELPFUL notes linked to at least one media.

    By default only notes not yet themed. With force=True, take recent attributed
    notes regardless (for reclassification after prompt changes).
    """
    with db_session() as conn:
        if force:
            rows = conn.execute(
                """
                SELECT DISTINCT n.note_id, n.summary
                FROM notes n
                JOIN note_media nm ON nm.note_id = n.note_id
                WHERE n.is_helpful = 1
                ORDER BY n.created_at_ms DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT DISTINCT n.note_id, n.summary
                FROM notes n
                JOIN note_media nm ON nm.note_id = n.note_id
                LEFT JOIN note_theme nt ON nt.note_id = n.note_id
                WHERE n.is_helpful = 1 AND nt.note_id IS NULL
                ORDER BY n.created_at_ms DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    out: list[dict[str, str]] = []
    for r in rows:
        summary = (r["summary"] or "").strip().replace("\n", " ")
        if len(summary) > 500:
            summary = summary[:497] + "…"
        out.append({"note_id": r["note_id"], "summary": summary})
    return out


def _classify_batch(batch: list[dict[str, str]], settings) -> dict[str, str]:
    payload_notes = [
        {"id": n["note_id"], "text": n["summary"] or ""} for n in batch
    ]
    user = (
        "Classe chaque note. JSON array attendu.\n\n"
        + json.dumps(payload_notes, ensure_ascii=False)
    )
    max_tokens = min(4000, 40 * len(batch) + 200)
    text = post_chat_completion(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        temperature=0.0,
        settings=settings,
    )
    data = _extract_json(text)
    if not isinstance(data, list):
        raise ValueError(f"expected JSON array, got {type(data)}")

    by_id = {n["note_id"]: "autre" for n in batch}
    for item in data:
        if not isinstance(item, dict):
            continue
        nid = str(item.get("id") or item.get("note_id") or "").strip()
        if nid not in by_id:
            continue
        by_id[nid] = normalize_theme(str(item.get("theme") or ""))
    return by_id


def store_themes(assignments: dict[str, str], *, model: str) -> int:
    if not assignments:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    rows = [(nid, theme, model, now) for nid, theme in assignments.items()]
    with db_session() as conn:
        conn.executemany(
            """
            INSERT INTO note_theme(note_id, theme, model, scored_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(note_id) DO UPDATE SET
                theme=excluded.theme,
                model=excluded.model,
                scored_at=excluded.scored_at
            """,
            rows,
        )
    return len(rows)


def classify_pending_notes(
    *,
    limit: int | None = None,
    batch_size: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Classify up to `limit` attributed notes. Idempotent storage (upsert)."""
    settings = get_settings()
    if not settings.openai_configured:
        return {
            "status": "skipped",
            "reason": "OPENAI_API_KEY unset",
            "classified": 0,
            "pending_left": None,
        }

    limit = limit if limit is not None else settings.theme_max_per_run
    batch_size = batch_size if batch_size is not None else settings.theme_batch_size
    batch_size = max(1, min(batch_size, 40))

    pending = pending_attributed_notes(limit, force=force)
    if not pending:
        return {
            "status": "ok",
            "classified": 0,
            "batches": 0,
            "model": settings.openai_model,
            "pending_left": 0,
            "force": force,
        }

    classified = 0
    errors: list[str] = []
    batches = 0
    for i in range(0, len(pending), batch_size):
        chunk = pending[i : i + batch_size]
        batches += 1
        try:
            mapping = _classify_batch(chunk, settings)
            classified += store_themes(mapping, model=settings.openai_model)
        except Exception as e:
            msg = f"batch@{i}: {e}"
            log.exception("theme classify failed: %s", msg)
            errors.append(msg[:300])
            continue

    with db_session() as conn:
        left = conn.execute(
            """
            SELECT COUNT(DISTINCT n.note_id) AS n
            FROM notes n
            JOIN note_media nm ON nm.note_id = n.note_id
            LEFT JOIN note_theme nt ON nt.note_id = n.note_id
            WHERE n.is_helpful = 1 AND nt.note_id IS NULL
            """
        ).fetchone()["n"]
        set_meta(conn, "last_theme_classify_at", datetime.now(timezone.utc).isoformat())
        set_meta(conn, "last_theme_classify_status", "ok" if not errors else "partial")

    return {
        "status": "ok" if not errors else "partial",
        "classified": classified,
        "batches": batches,
        "model": settings.openai_model,
        "pending_left": int(left),
        "force": force,
        "errors": errors[:10],
        "radar_themes": list(RADAR_THEMES),
    }
