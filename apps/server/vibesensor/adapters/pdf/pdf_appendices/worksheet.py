"""Worksheet and recapture appendix page rendering."""

from __future__ import annotations

from typing import TYPE_CHECKING

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.pdf_drawing import _draw_panel
from vibesensor.adapters.pdf.pdf_style import (
    FS_SMALL,
    GAP,
    MARGIN,
    PAGE_H,
    PAGE_W,
    PANEL_HEADER_H,
    SUB_CLR,
)
from vibesensor.adapters.pdf.pdf_text import (
    _draw_section_block,
    _draw_text,
)
from vibesensor.report_i18n import tr as _tr
from vibesensor.shared.boundaries.reporting.document import (
    AppendixAData,
    NextStep,
)

from .action_matrix import draw_action_steps_continuation_page, draw_action_steps_panel
from .guidance_page import draw_capture_guidance_page
from .layout import (
    _estimate_action_steps_panel_height,
    _estimate_worksheet_ranked_stack_height,
    _estimate_worksheet_top_panel_height,
)
from .tables import _draw_table
from .title_bar import draw_appendix_title_bar

__all__ = ["_appendix_a_page"]

if TYPE_CHECKING:
    from vibesensor.adapters.pdf.report_types import AppendixAPageRenderPlan


def _appendix_a_page(
    c: Canvas,
    plan: AppendixAPageRenderPlan,
) -> None:
    title_key = (
        "REPORT_RECAPTURE_GUIDANCE_TITLE"
        if plan.appendix.mode == "recapture"
        else "REPORT_APPENDIX_A_TITLE"
    )
    title_y = draw_appendix_title_bar(
        c,
        title=_tr(plan.lang, title_key),
        width=PAGE_W - 2 * MARGIN,
        page_top=PAGE_H - MARGIN,
    )
    if plan.appendix.mode == "recapture":
        draw_capture_guidance_page(c, plan, title_y)
    elif plan.continued:
        draw_action_steps_continuation_page(
            c,
            steps=list(plan.steps),
            lang=plan.lang,
            title_y=title_y,
            start_number=plan.start_number,
        )
    else:
        _draw_worksheet_page(
            c,
            plan.appendix,
            plan.lang,
            title_y,
            steps=list(plan.steps),
            start_number=plan.start_number,
        )


def _draw_worksheet_page(
    c: Canvas,
    appendix: AppendixAData,
    lang: str,
    title_y: float,
    *,
    steps: list[NextStep],
    start_number: int,
) -> None:
    width = PAGE_W - 2 * MARGIN
    top_h = _estimate_worksheet_top_panel_height(appendix, lang=lang)
    top_y = title_y - top_h
    _draw_panel(c, MARGIN, top_y, width, top_h, _tr(lang, "REPORT_PRIMARY_VS_ALTERNATIVE_TITLE"))
    block_x = MARGIN + 4 * mm
    block_y = top_y + top_h - PANEL_HEADER_H - 2 * mm
    col_gap = 6 * mm
    note_y = (
        _draw_text(
            c,
            block_x,
            block_y,
            width - 8 * mm,
            _tr(lang, "REPORT_SOURCE_CONFIDENCE_NOTE"),
            size=FS_SMALL,
            color=SUB_CLR,
            leading=FS_SMALL + 1.0,
            max_lines=2,
        )
        - 1.2 * mm
    )
    left_col_w = (width - 8 * mm - col_gap) * 0.58
    right_col_w = width - 8 * mm - col_gap - left_col_w
    left_y = _draw_section_block(
        c,
        block_x,
        note_y,
        left_col_w,
        _tr(lang, "REPORT_PRIMARY_SOURCE_LABEL"),
        appendix.primary_source or _tr(lang, "UNKNOWN"),
        max_lines=2,
    )
    primary_inspect_first = (
        appendix.ranked_candidates[0].inspect_first if appendix.ranked_candidates else None
    )
    if primary_inspect_first:
        left_y = _draw_section_block(
            c,
            block_x,
            left_y,
            left_col_w,
            _tr(lang, "REPORT_INSPECT_FIRST_LABEL"),
            primary_inspect_first,
            max_lines=2,
        )
    if appendix.why_primary_first:
        _draw_section_block(
            c,
            block_x,
            left_y,
            left_col_w,
            _tr(lang, "REPORT_WHY_PRIMARY_FIRST_LABEL"),
            appendix.why_primary_first,
            max_lines=3,
        )

    right_x = block_x + left_col_w + col_gap
    right_y = note_y
    if appendix.alternative_source:
        right_y = _draw_section_block(
            c,
            right_x,
            right_y,
            right_col_w,
            _tr(lang, "REPORT_ALTERNATIVE_SOURCE_LABEL"),
            appendix.alternative_source,
            max_lines=2,
        )
    if appendix.why_alternative_next:
        right_y = _draw_section_block(
            c,
            right_x,
            right_y,
            right_col_w,
            _tr(lang, "REPORT_WHY_ALTERNATIVE_NEXT_LABEL"),
            appendix.why_alternative_next,
            max_lines=3,
        )
    if appendix.next_if_clean:
        _draw_section_block(
            c,
            right_x,
            right_y,
            right_col_w,
            _tr(lang, "REPORT_IF_PRIMARY_CLEAN_LABEL"),
            appendix.next_if_clean,
            max_lines=3,
        )

    stack_h = _estimate_worksheet_ranked_stack_height(appendix, lang=lang)
    show_ranked_stack = stack_h > 0.0
    if show_ranked_stack:
        stack_y = top_y - GAP - stack_h
        _draw_panel(
            c, MARGIN, stack_y, width, stack_h, _tr(lang, "REPORT_RANKED_SOURCE_STACK_TITLE")
        )
        stack_rows = [
            [
                row.source_name,
                row.inspect_first or _tr(lang, "UNKNOWN"),
                row.path_role or _tr(lang, "UNKNOWN"),
                row.reason or "",
            ]
            for row in appendix.ranked_candidates
        ]
        _draw_table(
            c,
            x=MARGIN + 4 * mm,
            y=stack_y + stack_h - 13 * mm,
            w=width - 8 * mm,
            y_bottom=stack_y + 4 * mm,
            headers=[
                _tr(lang, "REPORT_SOURCE_COLUMN"),
                _tr(lang, "REPORT_INSPECT_FIRST_LABEL"),
                _tr(lang, "REPORT_PATH_ROLE_COLUMN"),
                _tr(lang, "REPORT_REASON_COLUMN"),
            ],
            rows=stack_rows,
            col_widths=[0.20, 0.20, 0.18, 0.42],
            max_body_lines=2,
            overflow_text_template=_tr(
                lang,
                "REPORT_TABLE_MORE_ROWS_NOT_SHOWN",
                count="{count}",
            ),
            overflow_singular_text_template=_tr(
                lang,
                "REPORT_TABLE_MORE_ROW_NOT_SHOWN",
                count="{count}",
            ),
        )
        matrix_top = stack_y - GAP
    else:
        matrix_top = top_y - GAP

    max_matrix_h = matrix_top - (MARGIN + 8 * mm)
    matrix_h = min(max_matrix_h, _estimate_action_steps_panel_height(steps, width=width))
    matrix_y = matrix_top - matrix_h
    draw_action_steps_panel(
        c,
        steps=steps,
        lang=lang,
        x=MARGIN,
        y=matrix_y,
        w=width,
        h=matrix_h,
        start_number=start_number,
        title=_tr(lang, "REPORT_ACTION_MATRIX_TITLE"),
    )
