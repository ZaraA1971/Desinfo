"""Résout un modèle : override env, sinon llm-router (qualité/prix)."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("llm_pick")

_FALLBACK = {
    ("chatgpt", "cheap"): "gpt-5.4-nano",
    ("chatgpt", "standard"): "gpt-5.4-mini",
    ("chatgpt", "strong"): "gpt-5.5",
    ("chatgpt", "search"): "gpt-5.4-mini",
    ("gemini", "cheap"): "gemini-2.5-flash-lite",
    ("gemini", "standard"): "gemini-2.5-flash",
    ("gemini", "strong"): "gemini-2.5-pro",
    ("gemini", "search"): "gemini-2.5-flash-lite",
    ("claude", "cheap"): "claude-haiku-4-5-20251001",
    ("claude", "standard"): "claude-sonnet-5-5",
    ("claude", "strong"): "claude-opus-5-5",
    ("grok", "cheap"): "grok-4-1-fast",
    ("grok", "standard"): "grok-4-1-fast",
    ("grok", "search"): "grok-4.3",
}


def pick(family: str, role: str, *, env: str | None = None) -> str:
    if env:
        pinned = (os.getenv(env) or "").strip()
        if pinned:
            return pinned
    try:
        from llm_router import choisir_modele

        return choisir_modele(family, role)
    except Exception as exc:
        fb = _FALLBACK.get((family, role))
        if not fb:
            raise
        logger.warning("llm-router indisponible (%s) — fallback %s", exc, fb)
        return fb


def next_pick(family: str, role: str, after: str | None) -> str | None:
    try:
        from llm_router import suite_modele

        return suite_modele(family, role, after)
    except Exception:
        return None
