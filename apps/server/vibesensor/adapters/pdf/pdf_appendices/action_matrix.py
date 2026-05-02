"""Action-matrix rendering and pagination for Appendix A."""

from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.action_cards import (
    draw_detailed_action_card,
    estimate_detailed_action_card_height,
)
from vibesensor.adapters.pdf.pdf_drawing import _draw_panel, _hex
from vibesensor.adapters.pdf.pdf_style import (
    FONT,
    FONT_B,
    FS_SMALL,
    MARGIN,
    PAGE_W,
    PANEL_HEADER_H,
    REPORT_COLORS,
    SUB_CLR,
    TEXT_CLR,
)
from vibesensor.adapters.pdf.pdf_text import _draw_text
from vibesensor.report_i18n import tr as _tr
from vibesensor.shared.boundaries.reporting.document import AppendixAData, NextStep

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
    estimated_h = _estimate_action_steps_panel_height(steps, width=width)
    panel_h = max_panel_h if max_panel_h - estimated_h > 32 * mm else min(max_panel_h, estimated_h)
    panel_y = title_y - panel_h
    row_y = draw_action_steps_panel(
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
    _draw_continuation_closeout(
        c,
        lang=lang,
        x=MARGIN + 4 * mm,
        y_bottom=panel_y + 4 * mm,
        y_top=row_y - 2 * mm,
        w=width - 8 * mm,
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
) -> float:
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
    return float(row_y)


def _draw_continuation_closeout(
    c: Canvas,
    *,
    lang: str,
    x: float,
    y_bottom: float,
    y_top: float,
    w: float,
) -> None:
    available_h = y_top - y_bottom
    if available_h < 26 * mm:
        return
    h = available_h
    y = y_bottom
    c.setFillColor(_hex(REPORT_COLORS["surface"]))
    c.setStrokeColor(_hex(REPORT_COLORS["table_row_border"]))
    c.roundRect(x, y, w, h, 2.6 * mm, stroke=1, fill=1)
    c.setFillColor(_hex(TEXT_CLR))
    c.setFont(FONT_B, FS_SMALL)
    title_y = y + h - 4.2 * mm
    c.drawString(x + 3 * mm, title_y, _tr(lang, "REPORT_ACTION_MATRIX_CLOSEOUT_TITLE"))
    c.setFillColor(_hex(SUB_CLR))
    c.setFont(FONT, FS_SMALL)
    _draw_text(
        c,
        x + 3 * mm,
        title_y - 4.0 * mm,
        w - 6 * mm,
        _tr(lang, "REPORT_ACTION_MATRIX_CLOSEOUT_TEXT"),
        size=FS_SMALL,
        color=SUB_CLR,
        leading=FS_SMALL + 1.0,
        max_lines=2,
    )
    grid_top = title_y - 14.0 * mm
    grid_bottom = y + 4 * mm
    if grid_top - grid_bottom < 20 * mm:
        return

    items = (
        (
            "REPORT_ACTION_MATRIX_HANDOFF_REPEAT_TITLE",
            "REPORT_ACTION_MATRIX_HANDOFF_REPEAT_TEXT",
            REPORT_COLORS["brand"],
        ),
        (
            "REPORT_ACTION_MATRIX_HANDOFF_RECORD_TITLE",
            "REPORT_ACTION_MATRIX_HANDOFF_RECORD_TEXT",
            REPORT_COLORS["axis"],
        ),
        (
            "REPORT_ACTION_MATRIX_HANDOFF_COMPARE_TITLE",
            "REPORT_ACTION_MATRIX_HANDOFF_COMPARE_TEXT",
            REPORT_COLORS["success"],
        ),
        (
            "REPORT_ACTION_MATRIX_HANDOFF_GATE_TITLE",
            "REPORT_ACTION_MATRIX_HANDOFF_GATE_TEXT",
            REPORT_COLORS["warning_clean"],
        ),
    )
    cell_gap = 2.2 * mm
    cell_w = (w - cell_gap) / 2.0
    cell_h = (grid_top - grid_bottom - cell_gap) / 2.0
    for index, (title_key, text_key, accent) in enumerate(items):
        col = index % 2
        row = index // 2
        cell_x = x + (col * (cell_w + cell_gap))
        cell_y = grid_top - ((row + 1) * cell_h) - (row * cell_gap)
        _draw_handoff_item(
            c,
            lang=lang,
            title_key=title_key,
            text_key=text_key,
            accent=accent,
            x=cell_x,
            y=cell_y,
            w=cell_w,
            h=cell_h,
        )


def _draw_handoff_item(
    c: Canvas,
    *,
    lang: str,
    title_key: str,
    text_key: str,
    accent: str,
    x: float,
    y: float,
    w: float,
    h: float,
) -> None:
    c.setFillColor(_hex("#ffffff"))
    c.setStrokeColor(_hex(REPORT_COLORS["table_row_border"]))
    c.roundRect(x, y, w, h, 2.0 * mm, stroke=1, fill=1)
    c.setFillColor(_hex(accent))
    c.roundRect(x + 2.2 * mm, y + h - 5.0 * mm, 7.5 * mm, 1.2 * mm, 0.6 * mm, stroke=0, fill=1)
    title_y = y + h - 8.0 * mm
    c.setFillColor(_hex(TEXT_CLR))
    c.setFont(FONT_B, FS_SMALL)
    c.drawString(x + 3 * mm, title_y, _tr(lang, title_key))
    _draw_text(
        c,
        x + 3 * mm,
        title_y - 3.6 * mm,
        w - 6 * mm,
        _tr(lang, text_key),
        size=FS_SMALL,
        color=SUB_CLR,
        leading=FS_SMALL + 1.0,
        max_lines=3,
    )
