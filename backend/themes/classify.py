"""Classify attributed HELPFUL notes into thematic buckets via small LLM."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from backend.config import get_settings
from backend.db import db_session, set_meta
from backend.scoring.rank import WINDOW_DAYS, _ms_since
from backend.themes.openai_chat import post_chat_completion
from backend.themes.taxonomy import ALL_THEMES, RADAR_THEMES, normalize_theme

log = logging.getLogger("desinfo.themes.classify")

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)

SYSTEM_PROMPT = f"""Tu classes des Community Notes (X) en UNE thématique dominante.
Pour chaque item tu reçois le POST (tweet original) et la NOTE (correction Community Note).
Thèmes autorisés (ids exacts uniquement) :
{", ".join(ALL_THEMES)}

Règle d’or : classe selon le SUJET du POST corrigé par la NOTE (l’affirmation trompeuse), en t’appuyant sur les deux textes. Ne te fie pas au média cité ni à la langue. Si le post est absent, classe quand même à partir de la note.

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
1) Si une personnalité / un parti politique FR (ou candidat) est le sujet principal → politique — même si le contenu porte sur l’Ukraine, l’Europe, la Crimée, etc.
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


def _clip(text: str | None, limit: int = 500) -> str:
    s = (text or "").strip().replace("\n", " ")
    if len(s) > limit:
        return s[: limit - 1] + "…"
    return s


def _attributed_clause() -> str:
    return """
        (
          EXISTS (SELECT 1 FROM note_media nm WHERE nm.note_id = n.note_id)
          OR EXISTS (SELECT 1 FROM note_politician np WHERE np.note_id = n.note_id)
        )
    """


def _classify_window_key(window_key: str | None) -> str:
    key = (window_key or "7d").strip().lower()
    if key != "7d":
        raise ValueError("theme classification supports window 7d only (longer windows use stored themes)")
    return key


def pending_attributed_notes(
    limit: int,
    *,
    force: bool = False,
    window_key: str = "7d",
    note_ids: set[str] | None = None,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    """HELPFUL notes in the classify window (7d) linked to media or politician."""
    window_key = _classify_window_key(window_key)
    since_ms = _ms_since(WINDOW_DAYS[window_key], now)
    attributed = _attributed_clause()
    id_filter = ""
    id_params: list[Any] = []
    if note_ids is not None:
        if not note_ids:
            return []
        placeholders = ",".join("?" * len(note_ids))
        id_filter = f" AND n.note_id IN ({placeholders})"
        id_params = list(note_ids)
    with db_session() as conn:
        if force:
            rows = conn.execute(
                f"""
                SELECT DISTINCT n.note_id, n.summary, n.tweet_id
                FROM notes n
                WHERE n.is_helpful = 1
                  AND n.created_at_ms >= ?
                  AND {attributed}
                  {id_filter}
                ORDER BY n.created_at_ms DESC
                LIMIT ?
                """,
                (since_ms, *id_params, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                f"""
                SELECT DISTINCT n.note_id, n.summary, n.tweet_id
                FROM notes n
                LEFT JOIN note_theme nt ON nt.note_id = n.note_id
                WHERE n.is_helpful = 1
                  AND n.created_at_ms >= ?
                  AND nt.note_id IS NULL
                  AND {attributed}
                  {id_filter}
                ORDER BY n.created_at_ms DESC
                LIMIT ?
                """,
                (since_ms, *id_params, limit),
            ).fetchall()
    out: list[dict[str, str]] = []
    for r in rows:
        out.append(
            {
                "note_id": r["note_id"],
                "summary": _clip(r["summary"], 500),
                "tweet_id": (r["tweet_id"] or "").strip(),
            }
        )
    return out


def count_pending_themes(*, window_key: str = "7d", now: datetime | None = None) -> int:
    """Unclassified attributed notes in the classify window (default 7d)."""
    window_key = _classify_window_key(window_key)
    since_ms = _ms_since(WINDOW_DAYS[window_key], now)
    with db_session() as conn:
        return int(
            conn.execute(
                f"""
                SELECT COUNT(DISTINCT n.note_id) AS n
                FROM notes n
                LEFT JOIN note_theme nt ON nt.note_id = n.note_id
                WHERE n.is_helpful = 1
                  AND n.created_at_ms >= ?
                  AND nt.note_id IS NULL
                  AND {_attributed_clause()}
                """,
                (since_ms,),
            ).fetchone()["n"]
        )


def _classify_batch(batch: list[dict[str, str]], settings) -> dict[str, str]:
    from backend.themes.tweets import ensure_tweet_texts

    tweet_ids = [n["tweet_id"] for n in batch if n.get("tweet_id")]
    posts = ensure_tweet_texts(tweet_ids) if tweet_ids else {}

    payload_notes = []
    for n in batch:
        tid = n.get("tweet_id") or ""
        post = _clip(posts.get(tid), 500) if tid else ""
        payload_notes.append(
            {
                "id": n["note_id"],
                "post": post or None,
                "note": n.get("summary") or "",
            }
        )
    user = (
        "Classe chaque item (post = tweet original, note = Community Note). "
        "JSON array attendu.\n\n"
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
    window_key: str = "7d",
    note_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Classify attributed notes in the current 7d window only (weekly moisson)."""
    settings = get_settings()
    if not settings.openai_configured:
        return {
            "status": "skipped",
            "reason": "OPENAI_API_KEY unset",
            "classified": 0,
            "pending_left": None,
        }

    window_key = _classify_window_key(window_key)
    limit = limit if limit is not None else settings.theme_max_per_run
    batch_size = batch_size if batch_size is not None else settings.theme_batch_size
    batch_size = max(1, min(batch_size, 40))

    pending = pending_attributed_notes(
        limit, force=force, window_key=window_key, note_ids=note_ids
    )
    if not pending:
        return {
            "status": "ok",
            "classified": 0,
            "batches": 0,
            "model": settings.openai_model,
            "pending_left": count_pending_themes(window_key=window_key),
            "window": window_key,
            "force": force,
            "incremental_note_ids": note_ids is not None,
        }

    # Prefetch tweet texts once per run (fetch mode) — fewer round-trips
    if settings.theme_x_fetch == "fetch":
        from backend.themes.tweets import ensure_tweet_texts

        all_tids = [n["tweet_id"] for n in pending if n.get("tweet_id")]
        if all_tids:
            ensure_tweet_texts(all_tids)

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
        left = count_pending_themes(window_key=window_key)
        set_meta(conn, "last_theme_classify_at", datetime.now(timezone.utc).isoformat())
        set_meta(conn, "last_theme_classify_status", "ok" if not errors else "partial")
        set_meta(conn, "last_theme_classify_window", window_key)

    return {
        "status": "ok" if not errors else "partial",
        "classified": classified,
        "batches": batches,
        "model": settings.openai_model,
        "pending_left": int(left),
        "window": window_key,
        "force": force,
        "incremental_note_ids": note_ids is not None,
        "errors": errors[:10],
        "radar_themes": list(RADAR_THEMES),
    }
