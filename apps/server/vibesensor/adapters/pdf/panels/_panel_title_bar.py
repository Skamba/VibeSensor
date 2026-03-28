"""Title-bar panel helper for PDF page 2."""

from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.pdf_drawing import _draw_panel, _hex
from vibesensor.adapters.pdf.pdf_style import (
    FONT_B,
    FS_TITLE,
    GAP,
    MARGIN,
    REPORT_COLORS,
    build_page2_layout,
)


def _draw_title_bar(c: Canvas, *, title: str, width: float, page_top: float) -> float:
    layout = build_page2_layout(
        width=width,
        page_top=page_top,
        has_transient_findings=False,
        has_next_steps_continued=False,
    )
    _draw_panel(
        c,
        layout.title_bar.x,
        layout.title_bar.y,
        layout.title_bar.w,
        layout.title_bar.h,
        fill=REPORT_COLORS["brand_surface"],
    )
    c.setFillColor(_hex(REPORT_COLORS["brand"]))
    c.setFont(FONT_B, FS_TITLE)
    c.drawString(MARGIN + 4 * mm, layout.title_bar.y + 3.5 * mm, title)
    return float(layout.title_bar.y - GAP)
