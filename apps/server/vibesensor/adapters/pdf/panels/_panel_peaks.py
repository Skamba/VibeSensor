"""Peaks-table panel helpers for PDF page 2."""

from __future__ import annotations

from collections.abc import Callable

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.pdf_drawing import _hex
from vibesensor.adapters.pdf.pdf_style import (
    FONT,
    FONT_B,
    LINE_CLR,
    MUTED_CLR,
    PANEL_BG,
    SOFT_BG,
    SUB_CLR,
    TEXT_CLR,
)
from vibesensor.adapters.pdf.report_data import ReportTemplateData


def _draw_peaks_table(
    c: Canvas,
    x: float,
    y_top: float,
    w: float,
    y_bottom: float,
    data: ReportTemplateData,
    tr: Callable[[str], str],
) -> None:
    """Diagnostic-first peaks table."""
    col_defs = [
        (tr("RANK"), 12 * mm),
        (tr("SYSTEM"), 24 * mm),
        (tr("FREQUENCY_HZ"), 18 * mm),
        (tr("ORDER_LABEL"), 24 * mm),
        (tr("PEAK_DB"), 18 * mm),
        (tr("STRENGTH_DB"), 16 * mm),
        (tr("SPEED_BAND"), 22 * mm),
    ]
    used = sum(col_w for _, col_w in col_defs)
    notes_w = max(20 * mm, w - used)
    col_defs.append((tr("MEANING"), notes_w))

    row_h = 6.2 * mm
    y = y_top

    c.setFillColor(_hex(SOFT_BG))
    c.setStrokeColor(_hex(LINE_CLR))
    c.rect(x, y - row_h + 1, w, row_h, stroke=1, fill=1)
    c.setFillColor(_hex(SUB_CLR))
    c.setFont(FONT_B, 6.5)
    cx_off = x + 1.5
    for label, col_w in col_defs:
        c.drawString(cx_off, y - 4.2 * mm, label)
        cx_off += col_w

    c.setFont(FONT, 6.5)
    rows = data.peak_rows
    if not rows:
        y -= row_h
        c.setFillColor(_hex(PANEL_BG))
        c.rect(x, y - row_h + 1, w, row_h, stroke=1, fill=1)
        c.setFillColor(_hex(MUTED_CLR))
        c.drawString(x + 2, y - 4.2 * mm, "—")
        return

    soft_bg = _hex(SOFT_BG)
    panel_bg = _hex(PANEL_BG)
    text_clr = _hex(TEXT_CLR)
    y_off = 4.2 * mm
    for idx, row in enumerate(rows, start=1):
        y -= row_h
        if y - row_h < y_bottom:
            break
        c.setFillColor(soft_bg if idx % 2 == 0 else panel_bg)
        c.rect(x, y - row_h + 1, w, row_h, stroke=1, fill=1)
        c.setFillColor(text_clr)
        cx_off = x + 1.5
        row_y = y - y_off
        for value, (_, col_w) in zip(
            (
                row.rank,
                row.system,
                row.freq_hz,
                row.order,
                row.peak_db,
                row.strength_db,
                row.speed_band,
                row.relevance,
            ),
            col_defs,
            strict=True,
        ):
            c.drawString(cx_off, row_y, value)
            cx_off += col_w
