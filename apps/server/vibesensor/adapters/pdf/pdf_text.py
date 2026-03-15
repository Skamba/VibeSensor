"""Text measurement, wrapping, and label/value drawing helpers."""

from __future__ import annotations

import textwrap

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from .pdf_drawing import _hex
from .pdf_style import (
    _HELVETICA_AVG_CHAR_RATIO,
    FONT,
    FONT_B,
    FS_BODY,
    FS_SMALL,
    SUB_CLR,
    TEXT_CLR,
)


def _wrap_lines(text: str, width_pt: float, font_size: float) -> list[str]:
    """Split *text* into lines estimated to fit within *width_pt*."""
    avg_char_w = font_size * _HELVETICA_AVG_CHAR_RATIO
    max_chars = max(10, int(width_pt / avg_char_w))
    lines: list[str] = []
    for paragraph in text.split("\n"):
        lines.extend(textwrap.wrap(paragraph, width=max_chars) or [""])
    return lines


def _draw_text(
    c: Canvas,
    x: float,
    y_top: float,
    w: float,
    text: str,
    *,
    font: str = FONT,
    size: float = FS_BODY,
    color: str = TEXT_CLR,
    leading: float | None = None,
    max_lines: int | None = None,
) -> float:
    """Draw wrapped text top-down and return the y after the last line."""
    if leading is None:
        leading = size + 2
    lines = _wrap_lines(text, w, size)
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
    c.setFillColor(_hex(color))
    c.setFont(font, size)
    y = y_top
    for line in lines:
        c.drawString(x, y, line)
        y -= leading
    return y


def _draw_kv(
    c: Canvas,
    x: float,
    y: float,
    label: str,
    value: str,
    *,
    label_w: float,
    fs: float = FS_BODY,
    value_w: float | None = None,
) -> float:
    """Draw a label/value pair and return the y below the rendered block."""
    c.setFillColor(_hex(SUB_CLR))
    c.setFont(FONT, fs)
    c.drawString(x, y, f"{label}:")
    c.setFillColor(_hex(TEXT_CLR))
    value_font = FONT_B if fs >= 8 else FONT
    c.setFont(value_font, fs)
    if value_w is not None:
        lines = _wrap_lines(value, value_w, fs)
        leading = fs + 2
        vy = y
        for line in lines:
            c.drawString(x + label_w, vy, line)
            vy -= leading
        return vy
    c.drawString(x + label_w, y, value)
    return y - (fs + 2)


def _kv_consumed_height(value: str, *, fs: float = FS_BODY, value_w: float | None = None) -> float:
    """Return vertical space consumed by a key/value value block."""
    leading = fs + 2
    if value_w is None:
        return leading
    return max(len(_wrap_lines(value, value_w, fs)), 1) * leading


def _draw_kv_column(
    c: Canvas,
    x: float,
    y_start: float,
    rows: list[tuple[str, str, float]],
    col_w: float,
    row_gap: float,
) -> float:
    """Draw a column of label/value pairs and return the ending y."""
    y = y_start
    for idx, (label, value, label_w) in enumerate(rows):
        value_w = max(20 * mm, col_w - label_w)
        y = _draw_kv(
            c,
            x,
            y,
            label,
            value,
            label_w=label_w,
            fs=FS_BODY,
            value_w=value_w,
        )
        if idx < len(rows) - 1:
            y -= row_gap
    return y


def _draw_section_block(
    c: Canvas,
    x: float,
    y: float,
    w: float,
    title: str,
    body: str,
    *,
    title_gap: float = 3.2 * mm,
    body_gap: float = 1.5 * mm,
    max_lines: int = 4,
) -> float:
    """Draw a title line followed by wrapped body text and return the next y."""
    c.setFillColor(_hex(TEXT_CLR))
    c.setFont(FONT_B, FS_SMALL)
    c.drawString(x, y, title)
    y -= title_gap
    y = _draw_text(c, x, y, w, body, size=FS_SMALL, color=SUB_CLR, max_lines=max_lines)
    y -= body_gap
    return y
