"""Action-matrix rendering and pagination for Appendix A."""

from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.action_cards import (
    draw_detailed_action_card,
    estimate_detailed_action_card_height,
)
from vibesensor.adapters.pdf.pdf_drawing import _draw_panel
from vibesensor.adapters.pdf.pdf_style import MARGIN, PAGE_W, PANEL_HEADER_H
from vibesensor.adapters.pdf.report_data import AppendixAData, NextStep
from vibesensor.report_i18n import tr as _tr

from .layout import (
    _estimate_action_steps_panel_height,
    _fit_action_steps,
    _worksheet_continuation_panel_height,
    _worksheet_first_actions_panel_height,
)

__all__ = [
    "draw_action_steps_continuation_page",
    "draw_action_steps_panel",
    "worksheet_step_pages",
]


def worksheet_step_pages(
    appendix: AppendixAData,
    steps: list[NextStep],
    *,
    lang: str,
) -> list[list[NextStep]]:
    """Split Appendix-A workflow steps into renderable pages."""

    if not steps:
        return [[]]

    width = PAGE_W - 2 * MARGIN
    first_panel_h = _worksheet_first_actions_panel_height(appendix, lang=lang)
    continuation_panel_h = _worksheet_continuation_panel_height()

    pages: list[list[NextStep]] = []
    remaining = list(steps)

    first_count = _fit_action_steps(remaining, panel_w=width, panel_h=first_panel_h)
    if first_count <= 0:
        first_count = 1
    pages.append(remaining[:first_count])
    remaining = remaining[first_count:]

    while remaining:
        count = _fit_action_steps(remaining, panel_w=width, panel_h=continuation_panel_h)
        if count <= 0:
            count = 1
        pages.append(remaining[:count])
        remaining = remaining[count:]
    return pages


def draw_action_steps_continuation_page(
    c: Canvas,
    *,
    steps: list[NextStep],
    lang: str,
    title_y: float,
    start_number: int,
) -> None:
    """Draw a continuation page that contains only the action matrix."""

    width = PAGE_W - 2 * MARGIN
    max_panel_h = title_y - (MARGIN + 8 * mm)
    panel_h = min(max_panel_h, _estimate_action_steps_panel_height(steps, width=width))
    panel_y = title_y - panel_h
    draw_action_steps_panel(
        c,
        steps=steps,
        lang=lang,
        x=MARGIN,
        y=panel_y,
        w=width,
        h=panel_h,
        start_number=start_number,
        title=_tr(lang, "REPORT_ACTION_MATRIX_TITLE"),
    )


def draw_action_steps_panel(
    c: Canvas,
    *,
    steps: list[NextStep],
    lang: str,
    x: float,
    y: float,
    w: float,
    h: float,
    start_number: int,
    title: str,
) -> None:
    """Draw the numbered Appendix-A action matrix."""

    _draw_panel(c, x, y, w, h, title)
    row_y = y + h - PANEL_HEADER_H - 2 * mm
    for index, step in enumerate(steps, start=start_number):
        estimated_h = estimate_detailed_action_card_height(step, width=w - 8 * mm)
        if row_y - estimated_h < y + 4 * mm:
            break
        row_y = draw_detailed_action_card(
            c,
            lang=lang,
            step=step,
            index=index,
            x=x + 4 * mm,
            y_top=row_y,
            w=w - 8 * mm,
        )
