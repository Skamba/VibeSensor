"""Recapture-guidance rendering for Appendix A."""

from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.models import ReportTemplateData
from vibesensor.adapters.pdf.pdf_drawing import _draw_panel
from vibesensor.adapters.pdf.pdf_style import FS_BODY, GAP, MARGIN, PAGE_W, PANEL_HEADER_H, TEXT_CLR
from vibesensor.adapters.pdf.pdf_text import _draw_text
from vibesensor.report_i18n import tr as _tr

from .tables import _draw_traceability_row

__all__ = ["draw_capture_guidance_page"]


def draw_capture_guidance_page(c: Canvas, data: ReportTemplateData, title_y: float) -> None:
    """Draw the recapture-guidance variant of Appendix A."""

    appendix = data.appendix_a
    appendix_d = data.appendix_d
    lang = data.lang
    width = PAGE_W - 2 * MARGIN
    panel_h = 40 * mm
    top_y = title_y - panel_h
    labels = [
        (_tr(lang, "REPORT_CAPTURE_ISSUES_TITLE"), appendix.capture_issues),
        (_tr(lang, "REPORT_CAPTURE_CHANGES_TITLE"), appendix.capture_changes),
        (_tr(lang, "REPORT_CAPTURE_CONDITIONS_TITLE"), appendix.capture_conditions),
    ]
    current_y = top_y
    for title, lines in labels:
        _draw_panel(c, MARGIN, current_y, width, panel_h, title)
        text = "\n".join(f"- {line}" for line in lines[:5]) or _tr(lang, "UNKNOWN")
        _draw_text(
            c,
            MARGIN + 4 * mm,
            current_y + panel_h - PANEL_HEADER_H - 2 * mm,
            width - 8 * mm,
            text,
            size=FS_BODY,
            color=TEXT_CLR,
            leading=FS_BODY + 1.4,
            max_lines=8,
        )
        current_y -= panel_h + GAP
    trace_panel_y = MARGIN + 8 * mm
    trace_panel_h = current_y - trace_panel_y
    if trace_panel_h <= 20 * mm or not appendix_d.rows:
        return
    _draw_panel(
        c,
        MARGIN,
        trace_panel_y,
        width,
        trace_panel_h,
        _tr(lang, "REPORT_TRACEABILITY_PANEL_TITLE"),
    )
    left_x = MARGIN + 4 * mm
    right_x = MARGIN + (width / 2) + 2 * mm
    left_y = trace_panel_y + trace_panel_h - PANEL_HEADER_H - 2 * mm
    right_y = left_y
    mid = (len(appendix_d.rows) + 1) // 2
    for row in appendix_d.rows[:mid]:
        left_y = (
            _draw_traceability_row(c, row, x=left_x, y=left_y, w=(width / 2) - 8 * mm) - 1.0 * mm
        )
    for row in appendix_d.rows[mid:]:
        right_y = (
            _draw_traceability_row(c, row, x=right_x, y=right_y, w=(width / 2) - 8 * mm) - 1.0 * mm
        )
