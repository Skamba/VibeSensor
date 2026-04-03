"""Shared title-bar renderer for appendix pages."""

from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.pdf_drawing import _draw_panel, _hex
from vibesensor.adapters.pdf.pdf_style import FONT_B, FS_TITLE, GAP, MARGIN, REPORT_COLORS

_TITLE_BAR_HEIGHT = 12 * mm


def draw_appendix_title_bar(
    c: Canvas,
    *,
    title: str,
    width: float,
    page_top: float,
) -> float:
    title_y = page_top - _TITLE_BAR_HEIGHT
    _draw_panel(
        c,
        MARGIN,
        title_y,
        width,
        _TITLE_BAR_HEIGHT,
        fill=REPORT_COLORS["brand_surface"],
    )
    c.setFillColor(_hex(REPORT_COLORS["brand"]))
    c.setFont(FONT_B, FS_TITLE)
    c.drawString(MARGIN + 4 * mm, title_y + 3.5 * mm, title)
    return float(title_y - GAP)
