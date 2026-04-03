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
from vibesensor.adapters.pdf.pdf_drawing import _draw_panel
from vibesensor.adapters.pdf.pdf_style import FS_BODY, FS_SMALL, PANEL_HEADER_H, SUB_CLR
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
    if not plan.next_steps:
        content_h += _measure_text_height(tr("NO_NEXT_STEPS"), w=content_w, size=FS_BODY)
    else:
        shown_steps = plan.next_steps[:2]
        for index, step in enumerate(shown_steps):
            content_h += estimate_compact_action_card_height(
                title=step.action,
                why=None,
                width=content_w,
            )
            if index < len(shown_steps) - 1:
                content_h += 2.5 * mm
        if len(plan.next_steps) > len(shown_steps):
            content_h += 0.5 * mm + _measure_text_height(
                tr("REPORT_ACTIONS_PAGE1_MORE"),
                w=content_w,
                size=FS_SMALL,
                leading=FS_SMALL + 1.0,
                max_lines=2,
            )
    return float(max(38 * mm, PANEL_HEADER_H + 2 * mm + content_h + 4 * mm))


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

    row_y = inner_y
    shown_steps = plan.next_steps[:2]
    for index, step in enumerate(shown_steps, start=1):
        estimated_h = estimate_compact_action_card_height(
            title=step.action,
            why=None,
            width=w - 8 * mm,
        )
        if row_y - estimated_h < y + 4 * mm:
            break
        row_y = draw_compact_action_card(
            c,
            index=index,
            title=step.action,
            why=None,
            x=inner_x,
            y_top=row_y,
            w=w - 8 * mm,
        )
    if len(plan.next_steps) > len(shown_steps) and row_y > y + 10 * mm:
        _draw_text(
            c,
            inner_x,
            row_y - 0.5 * mm,
            w - 8 * mm,
            tr("REPORT_ACTIONS_PAGE1_MORE"),
            size=FS_SMALL,
            color=SUB_CLR,
            leading=FS_SMALL + 1.0,
            max_lines=2,
        )
