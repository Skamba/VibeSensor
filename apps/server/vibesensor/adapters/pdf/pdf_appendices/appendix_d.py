"""Appendix D page rendering."""

from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.shared.boundaries.reporting.document import ReportTemplateData
from vibesensor.adapters.pdf.panels._panel_title_bar import _draw_title_bar
from vibesensor.adapters.pdf.pdf_drawing import _draw_panel
from vibesensor.adapters.pdf.pdf_style import MARGIN, PAGE_H, PAGE_W, PANEL_HEADER_H
from vibesensor.report_i18n import tr as _tr

from .tables import _draw_traceability_row

__all__ = ["_appendix_d_page"]


def _appendix_d_page(c: Canvas, data: ReportTemplateData) -> None:
    title_y = _draw_title_bar(
        c,
        title=_tr(data.lang, "REPORT_APPENDIX_D_TITLE"),
        width=PAGE_W - 2 * MARGIN,
        page_top=PAGE_H - MARGIN,
    )
    appendix = data.appendix_d
    width = PAGE_W - 2 * MARGIN
    panel_h = title_y - (MARGIN + 8 * mm)
    panel_y = MARGIN + 8 * mm
    _draw_panel(
        c, MARGIN, panel_y, width, panel_h, _tr(data.lang, "REPORT_TRACEABILITY_PANEL_TITLE")
    )
    left_x = MARGIN + 4 * mm
    right_x = MARGIN + (width / 2) + 2 * mm
    left_y = panel_y + panel_h - PANEL_HEADER_H - 2 * mm
    right_y = left_y
    mid = (len(appendix.rows) + 1) // 2
    for row in appendix.rows[:mid]:
        left_y = (
            _draw_traceability_row(c, row, x=left_x, y=left_y, w=(width / 2) - 8 * mm) - 1.0 * mm
        )
    for row in appendix.rows[mid:]:
        right_y = (
            _draw_traceability_row(c, row, x=right_x, y=right_y, w=(width / 2) - 8 * mm) - 1.0 * mm
        )
