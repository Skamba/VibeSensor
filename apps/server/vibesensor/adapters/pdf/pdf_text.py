"""Text measurement, wrapping, and label/value drawing helpers."""

from __future__ import annotations

import textwrap

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.pdf_drawing import _hex
from vibesensor.adapters.pdf.pdf_style import (
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


def _truncate_single_line(text: str, width_pt: float, font_size: float) -> str:
    """Return *text* truncated to one wrapped line, adding ``...`` when needed."""
    lines = _wrap_lines(text, width_pt, font_size)
    if len(lines) <= 1:
        return text
    first_line = lines[0].rstrip()
    if len(first_line) <= 3:
        return "..."
    return f"{first_line[:-3].rstrip()}..."


def _measure_text_height(
    text: str,
    *,
    w: float,
    size: float = FS_BODY,
    leading: float | None = None,
    max_lines: int | None = None,
) -> float:
    """Estimate vertical space consumed by wrapped text."""
    if leading is None:
        leading = size + 2
    lines = _wrap_lines(text, w, size)
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
    return float(max(len(lines), 1) * leading)


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


def _measure_section_block_height(
    body: str,
    *,
    w: float,
    title_gap: float = 3.2 * mm,
    body_gap: float = 1.5 * mm,
    max_lines: int = 4,
) -> float:
    """Estimate vertical space consumed by a section block body."""
    return float(
        title_gap + _measure_text_height(body, w=w, size=FS_SMALL, max_lines=max_lines) + body_gap
    )
