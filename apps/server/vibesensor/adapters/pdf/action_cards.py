"""Shared numbered action-card rendering for the report workflow pages."""

from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.pdf_drawing import _hex
from vibesensor.adapters.pdf.pdf_style import (
    FONT_B,
    FS_BODY,
    FS_SMALL,
    REPORT_COLORS,
    SUB_CLR,
    TEXT_CLR,
)
from vibesensor.adapters.pdf.pdf_text import _draw_section_block, _draw_text, _wrap_lines
from vibesensor.report_i18n import tr as _tr
from vibesensor.shared.boundaries.reporting.document import NextStep

__all__ = [
    "draw_compact_action_card",
    "draw_detailed_action_card",
    "estimate_compact_action_card_height",
    "estimate_detailed_action_card_height",
]

COMPACT_ACTION_TITLE_SIZE = 8.4
COMPACT_ACTION_WHY_SIZE = 6.6


def _draw_card_shell(c: Canvas, *, x: float, y_top: float, w: float, h: float) -> None:
    c.setFillColor(_hex(REPORT_COLORS["surface"]))
    c.setStrokeColor(_hex(REPORT_COLORS["border"]))
    c.roundRect(x, y_top - h, w, h, 3 * mm, stroke=1, fill=1)


def _draw_card_badge(c: Canvas, *, x: float, y_top: float, index: int) -> None:
    c.setFillColor(_hex(REPORT_COLORS["brand_surface"]))
    c.setStrokeColor(_hex(REPORT_COLORS["brand_surface"]))
    c.roundRect(x + 2 * mm, y_top - 9.5 * mm, 7 * mm, 7 * mm, 2 * mm, stroke=1, fill=1)
    c.setFillColor(_hex(REPORT_COLORS["brand"]))
    c.setFont(FONT_B, COMPACT_ACTION_WHY_SIZE)
    c.drawCentredString(x + 5.5 * mm, y_top - 6.4 * mm, str(index))


def estimate_compact_action_card_height(
    *,
    title: str,
    why: str | None,
    width: float,
    show_badge: bool = True,
) -> float:
    """Return the compact page-1 preview card height."""

    text_w = width - (14 * mm if show_badge else 8 * mm)
    title_lines = _wrap_lines(title, text_w, COMPACT_ACTION_TITLE_SIZE)[:3]
    why_lines = _wrap_lines(why or "", text_w, COMPACT_ACTION_WHY_SIZE)[:3] if why else []
    return float(
        max(
            20 * mm,
            7.0 * mm
            + (len(title_lines) * (COMPACT_ACTION_TITLE_SIZE + 1.2))
            + (
                0
                if not why_lines
                else 1.0 * mm + (len(why_lines) * (COMPACT_ACTION_WHY_SIZE + 1.0))
            ),
        )
    )


def draw_compact_action_card(
    c: Canvas,
    *,
    index: int | None,
    title: str,
    why: str | None,
    x: float,
    y_top: float,
    w: float,
) -> float:
    """Draw one compact action card used on page 1."""

    show_badge = index is not None
    card_h = estimate_compact_action_card_height(
        title=title, why=why, width=w, show_badge=show_badge
    )
    _draw_card_shell(c, x=x, y_top=y_top, w=w, h=card_h)
    if show_badge:
        assert index is not None
        _draw_card_badge(c, x=x, y_top=y_top, index=index)
    content_x = x + (12 * mm if show_badge else 4 * mm)
    content_w = w - (16 * mm if show_badge else 8 * mm)
    cursor_y = _draw_text(
        c,
        content_x,
        y_top - 4.8 * mm,
        content_w,
        title,
        font=FONT_B,
        size=COMPACT_ACTION_TITLE_SIZE,
        color=TEXT_CLR,
        leading=COMPACT_ACTION_TITLE_SIZE + 1.2,
        max_lines=3,
    )
    if why:
        _draw_text(
            c,
            content_x,
            cursor_y - 0.2 * mm,
            content_w,
            why,
            size=COMPACT_ACTION_WHY_SIZE,
            color=SUB_CLR,
            leading=COMPACT_ACTION_WHY_SIZE + 1.0,
            max_lines=3,
        )
    return float(y_top - card_h - 2.5 * mm)


def estimate_detailed_action_card_height(step: NextStep, *, width: float) -> float:
    """Return the worksheet/appendix action-card height."""

    title_lines = _wrap_lines(step.action, width - 18 * mm, FS_BODY)[:2]
    why_lines = _wrap_lines(step.why or "", width - 12 * mm, FS_SMALL)[:3] if step.why else []
    detail_w = (width - 18 * mm) / 2
    confirm_lines = _wrap_lines(step.confirm or "", detail_w, FS_SMALL)[:3] if step.confirm else []
    falsify_lines = _wrap_lines(step.falsify or "", detail_w, FS_SMALL)[:3] if step.falsify else []
    bottom_lines = max(len(confirm_lines), len(falsify_lines), 1)
    return float(
        max(
            28 * mm,
            10 * mm
            + (len(title_lines) * (FS_BODY + 1.2))
            + (len(why_lines) * (FS_SMALL + 1.0))
            + 8 * mm
            + (bottom_lines * (FS_SMALL + 1.0)),
        )
    )


def draw_detailed_action_card(
    c: Canvas,
    *,
    lang: str,
    step: NextStep,
    index: int,
    x: float,
    y_top: float,
    w: float,
) -> float:
    """Draw one detailed worksheet/appendix action card."""

    card_h = estimate_detailed_action_card_height(step, width=w)
    _draw_card_shell(c, x=x, y_top=y_top, w=w, h=card_h)
    _draw_card_badge(c, x=x, y_top=y_top, index=index)

    content_x = x + 12 * mm
    content_w = w - 16 * mm
    cursor_y = _draw_text(
        c,
        content_x,
        y_top - 4.8 * mm,
        content_w,
        step.action,
        font=FONT_B,
        size=FS_BODY,
        color=TEXT_CLR,
        leading=FS_BODY + 1.2,
        max_lines=2,
    )
    if step.why:
        cursor_y = (
            _draw_text(
                c,
                content_x,
                cursor_y - 0.2 * mm,
                content_w,
                step.why,
                size=FS_SMALL,
                color=SUB_CLR,
                leading=FS_SMALL + 1.0,
                max_lines=3,
            )
            - 1.0 * mm
        )

    divider_y = cursor_y - 0.4 * mm
    c.setStrokeColor(_hex(REPORT_COLORS["table_row_border"]))
    c.line(content_x, divider_y, x + w - 4 * mm, divider_y)

    col_gap = 4 * mm
    detail_w = (content_w - col_gap) / 2
    _draw_section_block(
        c,
        content_x,
        divider_y - 3.2 * mm,
        detail_w,
        _tr(lang, "CONFIRM"),
        step.confirm or "—",
        max_lines=3,
    )
    _draw_section_block(
        c,
        content_x + detail_w + col_gap,
        divider_y - 3.2 * mm,
        detail_w,
        _tr(lang, "REPORT_FALSIFY_COLUMN"),
        step.falsify or "—",
        max_lines=3,
    )
    return float(y_top - card_h - 2.5 * mm)
