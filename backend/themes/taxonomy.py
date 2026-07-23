"""Taxonomie thématique pour le radar médias (forces/faiblesses)."""
from __future__ import annotations

# Axes radar (ordre d'affichage). Hors radar : "autre".
RADAR_THEMES: tuple[str, ...] = (
    "politique",
    "sante",
    "economie",
    "justice",
    "international",
    "science",
    "technologie",
    "faits_divers",
)

ALL_THEMES: tuple[str, ...] = (*RADAR_THEMES, "autre")

THEME_LABELS_FR: dict[str, str] = {
    "politique": "Politique",
    "sante": "Santé",
    "economie": "Économie",
    "justice": "Justice",
    "international": "International",
    "science": "Science",
    "technologie": "Technologie",
    "faits_divers": "Faits divers",
    "autre": "Autre",
}


def normalize_theme(raw: str | None) -> str:
    """Map free-form model output to a canonical theme id."""
    if not raw:
        return "autre"
    t = str(raw).strip().lower()
    t = (
        t.replace("é", "e")
        .replace("è", "e")
        .replace("ê", "e")
        .replace("à", "a")
        .replace("ù", "u")
        .replace("ç", "c")
        .replace(" ", "_")
        .replace("-", "_")
    )
    aliases = {
        "sante": "sante",
        "santé": "sante",
        "health": "sante",
        "economie": "economie",
        "économie": "economie",
        "economy": "economie",
        "faitsdivers": "faits_divers",
        "fait_divers": "faits_divers",
        "faits_divers": "faits_divers",
        "tech": "technologie",
        "technologie": "technologie",
        "technology": "technologie",
        "politics": "politique",
        "politique": "politique",
        "justice": "justice",
        "international": "international",
        "science": "science",
        "autre": "autre",
        "other": "autre",
        "misc": "autre",
    }
    if t in ALL_THEMES:
        return t
    return aliases.get(t, "autre")
