"""Shared page-1 rendering helpers."""

from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.pdf_drawing import _hex
from vibesensor.adapters.pdf.pdf_style import FONT, FONT_B, FS_SMALL, FS_TITLE, SUB_CLR, TEXT_CLR
from vibesensor.adapters.pdf.pdf_text import _wrap_lines

__all__ = ["draw_label_value"]


def draw_label_value(
    c: Canvas,
    *,
    x: float,
    y: float,
    width: float | None,
    label: str,
    value: str,
    value_font: str = FONT_B,
    value_size: float = FS_TITLE,
    max_lines: int = 2,
) -> float:
    """Draw one label/value pair and return the next cursor y-position."""

    c.setFillColor(_hex(SUB_CLR))
    c.setFont(FONT, FS_SMALL)
    c.drawString(x, y, label)
    c.setFillColor(_hex(TEXT_CLR))
    c.setFont(value_font, value_size)
    if width is None:
        c.drawString(x, y - 5.0 * mm, value)
        return float(y - 9.5 * mm)
    value_lines = _wrap_lines(value, width, value_size)[:max_lines] or [value]
    line_y = y - 5.0 * mm
    line_leading = value_size + 1.0
    for line in value_lines:
        c.drawString(x, line_y, line)
        line_y -= line_leading
    return float(line_y - 1.8 * mm)
