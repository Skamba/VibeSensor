"""Action preview rendering for report page 1."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.action_cards import (
    draw_compact_action_card,
    estimate_compact_action_card_height,
)
from vibesensor.adapters.pdf.pdf_drawing import _draw_panel, _hex
from vibesensor.adapters.pdf.pdf_style import (
    FONT_B,
    FS_BODY,
    FS_SMALL,
    PANEL_HEADER_H,
    SUB_CLR,
    TEXT_CLR,
)
from vibesensor.adapters.pdf.pdf_text import _draw_text, _measure_text_height

if TYPE_CHECKING:
    from vibesensor.adapters.pdf.report_types import Page1RenderPlan

__all__ = ["draw_actions_block", "estimate_actions_block_height"]


def estimate_actions_block_height(
    plan: Page1RenderPlan,
    *,
    tr: Callable[..., str],
    w: float,
) -> float:
    """Estimate the page-1 action preview panel height."""

    content_w = w - 8 * mm
    content_h = 0.0
    fallback = plan.verdict_page.fallback_path
    if not plan.next_steps:
        content_h += _measure_text_height(tr("NO_NEXT_STEPS"), w=content_w, size=FS_BODY)
    else:
        content_h += estimate_compact_action_card_height(
            title=plan.next_steps[0].action,
            why=None,
            width=content_w,
        )
        if fallback:
            content_h += 7.0 * mm + _measure_text_height(
                fallback,
                w=content_w,
                size=FS_BODY,
                leading=FS_BODY + 1.0,
                max_lines=2,
            )
    return float(max(30 * mm, PANEL_HEADER_H + 2 * mm + content_h + 4 * mm))


def draw_actions_block(
    c: Canvas,
    plan: Page1RenderPlan,
    *,
    tr: Callable[..., str],
    x: float,
    y: float,
    w: float,
    h: float,
) -> None:
    """Draw the page-1 action preview panel."""

    _draw_panel(c, x, y, w, h, tr("REPORT_ACTIONS_PANEL_TITLE"))
    inner_x = x + 4 * mm
    inner_y = y + h - PANEL_HEADER_H - 2 * mm
    if not plan.next_steps:
        _draw_text(
            c, inner_x, inner_y, w - 8 * mm, tr("NO_NEXT_STEPS"), size=FS_BODY, color=SUB_CLR
        )
        return

    row_y = draw_compact_action_card(
        c,
        index=1,
        title=plan.next_steps[0].action,
        why=None,
        x=inner_x,
        y_top=inner_y,
        w=w - 8 * mm,
    )
    fallback = plan.verdict_page.fallback_path
    if fallback and row_y > y + 7 * mm:
        c.setStrokeColor(_hex("#dcdfe6"))
        c.line(inner_x, row_y - 0.8 * mm, inner_x + w - 8 * mm, row_y - 0.8 * mm)
        c.setFillColor(_hex(TEXT_CLR))
        c.setFont(FONT_B, FS_SMALL)
        c.drawString(inner_x, row_y - 4.1 * mm, tr("REPORT_PAGE1_IF_CLEAN_LABEL"))
        _draw_text(
            c,
            inner_x,
            row_y - 8.1 * mm,
            w - 8 * mm,
            fallback,
            font=FONT_B,
            size=FS_BODY,
            color=TEXT_CLR,
            leading=FS_BODY + 1.0,
            max_lines=2,
        )
