"""PDF export with diagonal watermark."""
from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from typing import Any

from fpdf import FPDF

from backend.config import get_settings

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def validate_email(email: str) -> str:
    e = (email or "").strip().lower()
    if not e or not EMAIL_RE.match(e) or len(e) > 254:
        raise ValueError("Adresse e-mail invalide")
    return e


class RankingPDF(FPDF):
    def __init__(self, watermark: str):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.watermark = watermark
        self.set_auto_page_break(auto=True, margin=14)
        self.set_margins(left=12, top=12, right=12)

    def header(self) -> None:
        # Draw watermark without advancing the content cursor.
        self._draw_watermark()
        self.set_y(self.t_margin)

    def footer(self) -> None:
        self.set_y(-10)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(100, 100, 100)
        self.cell(0, 6, f"Page {self.page_no()}/{{nb}}", align="C")

    def _draw_watermark(self) -> None:
        with self.local_context():
            self.set_text_color(210, 210, 210)
            self.set_font("Helvetica", "B", 11)
            for y in (70, 150, 230):
                with self.rotation(32, x=105, y=y):
                    # text() does not move the write cursor (unlike cell)
                    self.text(x=18, y=y, text=self.watermark)


def build_ranking_pdf(snapshot: dict[str, Any], email: str) -> bytes:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%d %H:%M UTC")
    wm = _safe(f"{email}  |  {settings.public_url}  |  {stamp}")
    pdf = RankingPDF(watermark=wm)
    pdf.alias_nb_pages()
    pdf.add_page()

    kind = snapshot.get("kind") or "media"
    subtitle = (
        "Palmares Community Notes - candidats presidentielle 2027"
        if kind == "politicians"
        else "Palmares Community Notes - medias France"
    )
    entity_col = "Candidat" if kind == "politicians" else "Media"

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 7, _safe("Observatoire de la desinformation"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, _safe(subtitle), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)

    window = snapshot.get("window", "?")
    generated = snapshot.get("generated_at", "")
    mode = snapshot.get("metric_mode", "")
    pdf.set_font("Helvetica", "", 8)
    pdf.multi_cell(
        0,
        4,
        _safe(
            f"Fenetre : {window}  |  Mode : {mode}  |  Calcul : {generated}\n"
            f"Metrique : CN / Posts  |  Export : {email}  |  {settings.public_url}"
        ),
    )
    pdf.ln(2)

    # Table — compact
    col_w = [12, 58, 18, 22, 36, 34]  # sum = 180
    headers = ["Rang", entity_col, "CN", "Posts", "CN/Post", "Post/CN"]
    row_h = 5.2
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(230, 230, 230)
    for i, h in enumerate(headers):
        pdf.cell(col_w[i], row_h, h, border=1, fill=True, align="C")
    pdf.ln(row_h)

    pdf.set_font("Helvetica", "", 7.5)
    items = snapshot.get("items") or []
    for it in items:
        # Keep table header row when wrapping to a new page
        if pdf.get_y() + row_h > pdf.page_break_trigger:
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_fill_color(230, 230, 230)
            for i, h in enumerate(headers):
                pdf.cell(col_w[i], row_h, h, border=1, fill=True, align="C")
            pdf.ln(row_h)
            pdf.set_font("Helvetica", "", 7.5)

        rank = str(it.get("rank", ""))
        name = _safe((it.get("name") or "")[:34])
        cn = str(it.get("cn_count", ""))
        posts = "-" if it.get("post_count") is None else str(it.get("post_count"))
        rate = _fmt_rate(it.get("rate_cn_per_post"))
        ratio = _fmt_ratio(it.get("ratio_post_per_cn"))
        row = [rank, name, cn, posts, rate, ratio]
        for i, val in enumerate(row):
            align = "L" if i == 1 else ("C" if i == 0 else "R")
            pdf.cell(col_w[i], row_h, _safe(val), border=1, align=align)
        pdf.ln(row_h)

    pdf.ln(3)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(80, 80, 80)
    pdf.multi_cell(
        0,
        3.5,
        _safe(
            "Document watermarke. Toute redistribution doit conserver cette mention. "
            "Donnees Community Notes (X) — Observatoire Electron Libre."
        ),
    )

    out = pdf.output()
    if isinstance(out, bytearray):
        return bytes(out)
    if isinstance(out, bytes):
        return out
    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()


def _safe(text: str) -> str:
    # Helvetica core fonts: latin-1 only
    return (
        str(text)
        .replace("—", "-")
        .replace("–", "-")
        .replace("·", "|")
        .replace("é", "e")
        .replace("è", "e")
        .replace("ê", "e")
        .replace("à", "a")
        .replace("ù", "u")
        .replace("ô", "o")
        .replace("î", "i")
        .replace("ç", "c")
        .replace("É", "E")
        .replace("È", "E")
        .replace("À", "A")
        .replace("œ", "oe")
        .replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
        .encode("latin-1", "replace")
        .decode("latin-1")
    )


def _fmt_rate(n: Any) -> str:
    if n is None:
        return "-"
    try:
        v = float(n)
    except (TypeError, ValueError):
        return "-"
    return f"{v:.5f}"


def _fmt_ratio(n: Any) -> str:
    if n is None:
        return "-"
    try:
        v = float(n)
    except (TypeError, ValueError):
        return "-"
    if v >= 100:
        return f"{v:.1f}"
    return f"{v:.3f}"
