"""Classify attributed HELPFUL notes into thematic buckets via small LLM."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from backend.config import get_settings
from backend.db import SQLITE_IN_CHUNK, chunked, db_session, set_meta
from backend.scoring.rank import WINDOW_DAYS, cn_window_bounds, window_as_of
from backend.themes.openai_chat import post_chat_completion
from backend.themes.taxonomy import ALL_THEMES, RADAR_THEMES, normalize_theme

log = logging.getLogger("desinfo.themes.classify")

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)

SYSTEM_PROMPT = f"""Tu classes des Community Notes (X) en UNE thématique dominante.
Pour chaque item tu reçois le POST (tweet original) et la NOTE (correction Community Note).
Thèmes autorisés (ids exacts uniquement) :
{", ".join(ALL_THEMES)}

Critère unique (médias et personnalités) :
classe uniquement le sujet du fait corrigé. Qui parle (média, élu, parti, @handle) ne change jamais le thème. Une note sur un élu se classe exactement comme si le même fait venait d’un média.

Méthode (dans cet ordre) :
1) Quelle est l’affirmation trompeuse du POST ?
2) Que corrige réellement la NOTE — le cœur de la rectification ?
3) Choisis le thème de ce cœur, pas le décor (lieu, événement, marque, sport, personnalité citée, etc.).
Ne te fie pas au média cité, au compte auteur, ni à la langue. Si le post est absent, classe à partir de la note seule.

Règle anti-biais (critique) :
- La présence d’un·e politicien·ne, d’un parti ou d’un @handle politique N’EST PAS un motif pour choisir « politique ».
- Classe selon la substance du fait corrigé. Un élu qui parle du nucléaire, de l’Ukraine, d’un fake IA ou d’un prix → science / international / technologie / economie selon le cœur.
- « politique » seulement si le cœur est vraiment institutionnel/partisan : élections, mandats, carrière, votes au Parlement comme acte partisan, sondages d’intentions, appartenance/parti.

Définitions (par nature du sujet corrigé) :
- politique : élections, mandats, partis, gouvernement/parlement comme institutions, carrière politique, sondages d’intentions, discours purement partisans. PAS le simple fait qu’un élu soit cité. PAS une polémique de personne si un autre sujet factuel existe (Cuba, fake visuel, affaire judiciaire, compte X, etc.).
- sante : santé publique, médecine, vaccins, hôpitaux, épidémies, médicaments. Pas un fait divers avec blessé si le cœur n’est pas médical.
- economie : entreprises, marchés, finance, inflation, budget chiffré, emploi, commerce, subventions, coûts.
- justice : procédures judiciaires, tribunaux, peines, enquêtes formelles, procès. Crime isolé sans angle judiciaire → faits_divers.
- international : géopolitique, guerres, diplomatie, États, conflits, OTAN, Ukraine/Russie/Moyen-Orient — même si un politicien FR commente.
- science : recherche, climat/environnement scientifique, énergie nucléaire comme fait scientifique/technique, espace, études. Pseudo-science → science.
- technologie : média fabriqué / synthétique / IA, plateformes, cybersécurité, bugs, robots. Si la note porte sur l’artefact technique → technologie (même si un politicien apparaît sur l’image).
- faits_divers : accidents, incendies, crimes isolés, people/divertissement/sport comme sujet principal, scènes locales trompeuses.
- autre : meta-média, humour sans enjeu, ou vraiment hors des axes — seulement en dernier recours.

Ambiguïté : préférer le thème le plus spécifique au cœur de la correction ; autre en dernier recours.
Si un élément du décor (y compris un politicien) entre en conflit avec le cœur, le cœur gagne toujours.

Exemples de raisonnement :
- Élu FR qui commente l’Ukraine / la Crimée / l’OTAN → international (cœur = géopolitique)
- Élu FR + affirmation sur le nucléaire, le climat, les canicules → science
- Note qui établit surtout qu’un média est fabriqué / synthétique / truqué / pastiche → technologie (même si un politicien est sur l’image)
- Correction sur un coût, une subvention, un chiffre économique → economie
- Mandats cumulés, parachutage, sondage présidentiel, vote de parti → politique
- Condamnation / peine / tribunal / mise en examen / affaire judiciaire → justice
- Bilan d’un régime étranger (Castro, Cuba, droits humains) même cité par un élu FR → international
- Compte X toujours actif / visuel satirique / pastiche d’antenne → technologie
- Incendie local présenté à tort comme une attaque militaire → international si la tromperie porte sur le conflit ; faits_divers si le cœur est juste la mauvaise scène locale

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
    """Only the 7d window classifies. 30d/90d/365d reuse stored note_theme."""
    key = (window_key or "7d").strip().lower()
    if key != "7d":
        raise ValueError(
            f"theme classification is 7d only (longer windows reuse stored themes), got {window_key!r}"
        )
    return key


def _classify_window_filter(
    window_key: str, now: datetime | None = None
) -> tuple[str, list[Any]]:
    as_of = now or window_as_of(window_key)
    since_ms, until_ms = cn_window_bounds(WINDOW_DAYS[window_key], as_of)
    return "n.created_at_ms >= ? AND n.created_at_ms < ?", [since_ms, until_ms]


def _scope_filters(
    *,
    note_ids: set[str] | None = None,
    media_ids: set[str] | None = None,
    politician_ids: set[str] | None = None,
) -> tuple[str, list[Any]]:
    """Extra AND clauses + params for note / media / politician scoping.

    `note_ids` must already fit under SQLITE_IN_CHUNK (caller chunks if needed).
    """
    clauses: list[str] = []
    params: list[Any] = []
    if note_ids is not None:
        if not note_ids:
            return " AND 0", []
        placeholders = ",".join("?" * len(note_ids))
        clauses.append(f"n.note_id IN ({placeholders})")
        params.extend(note_ids)
    if media_ids:
        placeholders = ",".join("?" * len(media_ids))
        clauses.append(
            f"EXISTS (SELECT 1 FROM note_media nm "
            f"WHERE nm.note_id = n.note_id AND nm.media_id IN ({placeholders}))"
        )
        params.extend(media_ids)
    if politician_ids:
        placeholders = ",".join("?" * len(politician_ids))
        clauses.append(
            f"EXISTS (SELECT 1 FROM note_politician np "
            f"WHERE np.note_id = n.note_id AND np.politician_id IN ({placeholders}))"
        )
        params.extend(politician_ids)
    if not clauses:
        return "", []
    return " AND " + " AND ".join(clauses), params


def pending_attributed_notes(
    limit: int,
    *,
    force: bool = False,
    window_key: str = "7d",
    note_ids: set[str] | None = None,
    media_ids: set[str] | None = None,
    politician_ids: set[str] | None = None,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    """HELPFUL notes in the classify window linked to a media or politician."""
    window_key = _classify_window_key(window_key)
    win_sql, win_params = _classify_window_filter(window_key, now)
    attributed = _attributed_clause()

    if note_ids is not None and not note_ids:
        return []

    # Large ingest touch-sets exceed SQLITE_MAX_VARIABLE_NUMBER — query by chunks.
    id_chunks: list[set[str] | None]
    if note_ids is not None and len(note_ids) > SQLITE_IN_CHUNK:
        id_chunks = [set(chunk) for chunk in chunked(note_ids, SQLITE_IN_CHUNK)]
    else:
        id_chunks = [note_ids]

    seen: set[str] = set()
    out: list[dict[str, str]] = []
    with db_session() as conn:
        for chunk_ids in id_chunks:
            if len(out) >= limit:
                break
            scope_sql, scope_params = _scope_filters(
                note_ids=chunk_ids,
                media_ids=media_ids,
                politician_ids=politician_ids,
            )
            if scope_sql == " AND 0":
                continue
            remain = limit - len(out)
            if force:
                rows = conn.execute(
                    f"""
                    SELECT DISTINCT n.note_id, n.summary, n.tweet_id
                    FROM notes n
                    WHERE n.is_helpful = 1
                      AND {win_sql}
                      AND {attributed}
                      {scope_sql}
                    ORDER BY n.created_at_ms DESC
                    LIMIT ?
                    """,
                    (*win_params, *scope_params, remain),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    SELECT DISTINCT n.note_id, n.summary, n.tweet_id
                    FROM notes n
                    LEFT JOIN note_theme nt ON nt.note_id = n.note_id
                    WHERE n.is_helpful = 1
                      AND {win_sql}
                      AND nt.note_id IS NULL
                      AND {attributed}
                      {scope_sql}
                    ORDER BY n.created_at_ms DESC
                    LIMIT ?
                    """,
                    (*win_params, *scope_params, remain),
                ).fetchall()
            for r in rows:
                nid = r["note_id"]
                if nid in seen:
                    continue
                seen.add(nid)
                out.append(
                    {
                        "note_id": nid,
                        "summary": _clip(r["summary"], 500),
                        "tweet_id": (r["tweet_id"] or "").strip(),
                    }
                )
                if len(out) >= limit:
                    break
    return out

def count_pending_themes(*, window_key: str = "7d", now: datetime | None = None) -> int:
    """Unclassified attributed notes in the classify window (default 7d)."""
    window_key = _classify_window_key(window_key)
    win_sql, win_params = _classify_window_filter(window_key, now)
    with db_session() as conn:
        return int(
            conn.execute(
                f"""
                SELECT COUNT(DISTINCT n.note_id) AS n
                FROM notes n
                LEFT JOIN note_theme nt ON nt.note_id = n.note_id
                WHERE n.is_helpful = 1
                  AND {win_sql}
                  AND nt.note_id IS NULL
                  AND {_attributed_clause()}
                """,
                win_params,
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
    media_ids: set[str] | None = None,
    politician_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Classify notes that still have no theme. Weekly moisson uses the 7d window."""
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
    media_ids = {str(x) for x in media_ids} if media_ids else None
    politician_ids = {str(x) for x in politician_ids} if politician_ids else None

    pending = pending_attributed_notes(
        limit,
        force=force,
        window_key=window_key,
        note_ids=note_ids,
        media_ids=media_ids,
        politician_ids=politician_ids,
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
            "media_ids": sorted(media_ids) if media_ids else None,
            "politician_ids": sorted(politician_ids) if politician_ids else None,
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
        "media_ids": sorted(media_ids) if media_ids else None,
        "politician_ids": sorted(politician_ids) if politician_ids else None,
        "errors": errors[:10],
        "radar_themes": list(RADAR_THEMES),
    }
