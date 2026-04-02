"""Worksheet and recapture appendix page rendering."""

from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.panels._panel_title_bar import _draw_title_bar
from vibesensor.adapters.pdf.pdf_drawing import _draw_panel, _hex
from vibesensor.adapters.pdf.pdf_style import (
    FONT_B,
    FS_BODY,
    FS_SMALL,
    GAP,
    MARGIN,
    PAGE_H,
    PAGE_W,
    PANEL_HEADER_H,
    REPORT_COLORS,
    SUB_CLR,
    TEXT_CLR,
)
from vibesensor.adapters.pdf.pdf_text import (
    _draw_section_block,
    _draw_text,
)
from vibesensor.adapters.pdf.report_data import (
    AppendixAData,
    NextStep,
    ReportTemplateData,
)
from vibesensor.report_i18n import tr as _tr

from .layout import (
    _estimate_action_step_card_height,
    _estimate_action_steps_panel_height,
    _estimate_worksheet_ranked_stack_height,
    _estimate_worksheet_top_panel_height,
    _fit_action_steps,
    _worksheet_continuation_panel_height,
    _worksheet_first_actions_panel_height,
)
from .tables import _draw_table, _draw_traceability_row

__all__ = ["_appendix_a_page", "worksheet_step_pages"]


def _appendix_a_page(
    c: Canvas,
    data: ReportTemplateData,
    *,
    steps: list[NextStep] | None = None,
    start_number: int = 1,
    continued: bool = False,
) -> None:
    title_key = (
        "REPORT_RECAPTURE_GUIDANCE_TITLE"
        if data.appendix_a.mode == "recapture"
        else "REPORT_APPENDIX_A_TITLE"
    )
    title_y = _draw_title_bar(
        c,
        title=_tr(data.lang, title_key),
        width=PAGE_W - 2 * MARGIN,
        page_top=PAGE_H - MARGIN,
    )
    if data.appendix_a.mode == "recapture":
        _draw_capture_guidance_page(c, data, title_y)
    elif continued:
        _draw_action_steps_continuation_page(
            c,
            steps=steps or [],
            lang=data.lang,
            title_y=title_y,
            start_number=start_number,
        )
    else:
        _draw_worksheet_page(
            c,
            data.appendix_a,
            data,
            data.lang,
            title_y,
            steps=steps or data.next_steps,
            start_number=start_number,
        )


def worksheet_step_pages(
    appendix: AppendixAData, steps: list[NextStep], *, lang: str
) -> list[list[NextStep]]:
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


def _draw_capture_guidance_page(c: Canvas, data: ReportTemplateData, title_y: float) -> None:
    appendix = data.appendix_a
    appendix_d = data.appendix_d
    lang = data.lang
    width = PAGE_W - 2 * MARGIN
    panel_h = 40 * mm
    top_y = title_y - panel_h
    labels = [
        (_tr(lang, "REPORT_CAPTURE_ISSUES_TITLE"), appendix.capture_issues),
        (_tr(lang, "REPORT_CAPTURE_CHANGES_TITLE"), appendix.capture_changes),
        (_tr(lang, "REPORT_CAPTURE_CONDITIONS_TITLE"), appendix.capture_conditions),
    ]
    current_y = top_y
    for title, lines in labels:
        _draw_panel(c, MARGIN, current_y, width, panel_h, title)
        text = "\n".join(f"- {line}" for line in lines[:5]) or _tr(lang, "UNKNOWN")
        _draw_text(
            c,
            MARGIN + 4 * mm,
            current_y + panel_h - PANEL_HEADER_H - 2 * mm,
            width - 8 * mm,
            text,
            size=FS_BODY,
            color=TEXT_CLR,
            leading=FS_BODY + 1.4,
            max_lines=8,
        )
        current_y -= panel_h + GAP
    trace_panel_y = MARGIN + 8 * mm
    trace_panel_h = current_y - trace_panel_y
    if trace_panel_h <= 20 * mm or not appendix_d.rows:
        return
    _draw_panel(
        c,
        MARGIN,
        trace_panel_y,
        width,
        trace_panel_h,
        _tr(lang, "REPORT_TRACEABILITY_PANEL_TITLE"),
    )
    left_x = MARGIN + 4 * mm
    right_x = MARGIN + (width / 2) + 2 * mm
    left_y = trace_panel_y + trace_panel_h - PANEL_HEADER_H - 2 * mm
    right_y = left_y
    mid = (len(appendix_d.rows) + 1) // 2
    for row in appendix_d.rows[:mid]:
        left_y = (
            _draw_traceability_row(c, row, x=left_x, y=left_y, w=(width / 2) - 8 * mm) - 1.0 * mm
        )
    for row in appendix_d.rows[mid:]:
        right_y = (
            _draw_traceability_row(c, row, x=right_x, y=right_y, w=(width / 2) - 8 * mm) - 1.0 * mm
        )


def _draw_worksheet_page(
    c: Canvas,
    appendix: AppendixAData,
    data: ReportTemplateData,
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
        )
        matrix_top = stack_y - GAP
    else:
        matrix_top = top_y - GAP

    max_matrix_h = matrix_top - (MARGIN + 8 * mm)
    matrix_h = min(max_matrix_h, _estimate_action_steps_panel_height(steps, width=width))
    matrix_y = matrix_top - matrix_h
    _draw_action_steps_panel(
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


def _draw_action_steps_continuation_page(
    c: Canvas,
    *,
    steps: list[NextStep],
    lang: str,
    title_y: float,
    start_number: int,
) -> None:
    width = PAGE_W - 2 * MARGIN
    max_panel_h = title_y - (MARGIN + 8 * mm)
    panel_h = min(max_panel_h, _estimate_action_steps_panel_height(steps, width=width))
    panel_y = title_y - panel_h
    _draw_action_steps_panel(
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


def _draw_action_steps_panel(
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
    _draw_panel(c, x, y, w, h, title)
    row_y = y + h - PANEL_HEADER_H - 2 * mm
    for index, step in enumerate(steps, start=start_number):
        estimated_h = _estimate_action_step_card_height(step, width=w - 8 * mm)
        if row_y - estimated_h < y + 4 * mm:
            break
        row_y = _draw_action_step_card(
            c,
            lang=lang,
            step=step,
            index=index,
            x=x + 4 * mm,
            y_top=row_y,
            w=w - 8 * mm,
        )


def _draw_action_step_card(
    c: Canvas,
    *,
    lang: str,
    step: NextStep,
    index: int,
    x: float,
    y_top: float,
    w: float,
) -> float:
    card_h = _estimate_action_step_card_height(step, width=w)
    c.setFillColor(_hex(REPORT_COLORS["surface"]))
    c.setStrokeColor(_hex(REPORT_COLORS["border"]))
    c.roundRect(x, y_top - card_h, w, card_h, 3 * mm, stroke=1, fill=1)

    c.setFillColor(_hex(REPORT_COLORS["brand_surface"]))
    c.setStrokeColor(_hex(REPORT_COLORS["brand_surface"]))
    c.roundRect(x + 2 * mm, y_top - 9.5 * mm, 7 * mm, 7 * mm, 2 * mm, stroke=1, fill=1)
    c.setFillColor(_hex(REPORT_COLORS["brand"]))
    c.setFont(FONT_B, FS_SMALL)
    c.drawCentredString(x + 5.5 * mm, y_top - 6.4 * mm, str(index))

    content_x = x + 12 * mm
    content_w = w - 16 * mm
    cursor_y = y_top - 4.8 * mm
    cursor_y = _draw_text(
        c,
        content_x,
        cursor_y,
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
