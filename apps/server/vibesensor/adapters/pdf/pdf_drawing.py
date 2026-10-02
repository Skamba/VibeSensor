"""Low-level PDF drawing primitives and value-format helpers."""

from __future__ import annotations

from functools import lru_cache

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.pdf_style import (
    FONT,
    FONT_B,
    FS_H2,
    FS_SMALL,
    LINE_CLR,
    MARGIN,
    MUTED_CLR,
    PAGE_W,
    PANEL_BG,
    R_CARD,
    TEXT_CLR,
)


@lru_cache(maxsize=32)
def _hex(c: str) -> colors.Color:
    """Return a cached ReportLab color instance."""
    return colors.HexColor(c)


def _safe(v: str | None, fallback: str = "\u2014") -> str:
    """Return *v* stripped if non-empty, otherwise *fallback*."""
    if v:
        s = str(v).strip()
        if s:
            return s
    return fallback


def _draw_panel(
    c: Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    title: str | None = None,
    fill: str = PANEL_BG,
    border: str = LINE_CLR,
) -> None:
    """Draw a rounded panel rectangle, optionally with a title."""
    c.setFillColor(_hex(fill))
    c.setStrokeColor(_hex(border))
    c.roundRect(x, y, w, h, R_CARD, stroke=1, fill=1)
    if title:
        c.setFillColor(_hex(TEXT_CLR))
        c.setFont(FONT_B, FS_H2)
        c.drawString(x + 4 * mm, y + h - 5.5 * mm, title)


def _draw_footer(c: Canvas, page_num: int, total: int, footer_title: str | None) -> None:
    """Draw the report footer with production-facing title and page counter."""
    y = MARGIN - 4 * mm
    c.setFont(FONT, FS_SMALL)
    c.setFillColor(_hex(MUTED_CLR))
    if footer_title:
        c.drawString(MARGIN, y, footer_title)
    c.drawRightString(PAGE_W - MARGIN, y, f"{page_num} / {total}")
