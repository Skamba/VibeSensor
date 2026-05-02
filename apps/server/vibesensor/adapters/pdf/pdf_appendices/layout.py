"""Compact panel and table sizing for report appendices."""

from __future__ import annotations

from typing import TYPE_CHECKING

from reportlab.lib.units import mm

from vibesensor.adapters.pdf.action_cards import estimate_detailed_action_card_height
from vibesensor.adapters.pdf.pdf_style import (
    FS_BODY,
    FS_SMALL,
    GAP,
    MARGIN,
    PAGE_H,
    PAGE_W,
    PANEL_HEADER_H,
)
from vibesensor.adapters.pdf.pdf_text import (
    _measure_section_block_height,
    _measure_text_height,
    _wrap_lines,
)
from vibesensor.report_i18n import tr as _tr
from vibesensor.shared.boundaries.reporting.document import (
    AppendixAData,
    NextStep,
    ReportLabelValueRow,
)

if TYPE_CHECKING:
    from vibesensor.adapters.pdf.report_types import AppendixCRenderPlan

__all__ = [
    "_estimate_action_steps_panel_height",
    "_estimate_appendix_c_context_panel_height",
    "_estimate_appendix_c_suitability_panel_height",
    "_estimate_appendix_c_trace_panel_height",
    "_estimate_worksheet_ranked_stack_height",
    "_estimate_worksheet_top_panel_height",
    "_worksheet_first_actions_panel_height",
]


def _estimate_appendix_c_traceability_row_height(
    row: ReportLabelValueRow, *, width: float
) -> float:
    return float(
        3.4 * mm
        + _measure_text_height(
            row.value,
            w=width,
            size=FS_BODY,
            leading=FS_BODY + 1.2,
            max_lines=3,
        )
        + 0.4 * mm
    )


def _estimate_appendix_c_context_panel_height(plan: AppendixCRenderPlan, *, width: float) -> float:
    appendix_c = plan.appendix
    content_w = width - 8 * mm
    total = PANEL_HEADER_H + 2 * mm
    if appendix_c.context_summary:
        total += (
            _measure_text_height(
                appendix_c.context_summary,
                w=content_w,
                size=FS_SMALL,
                leading=FS_SMALL + 1.0,
                max_lines=4,
            )
            + 1.2 * mm
        )
    for snapshot in appendix_c.evidence_snapshot_rows[:5]:
        total += _measure_section_block_height(snapshot.value, w=content_w, max_lines=3)
    total += _measure_section_block_height(
        appendix_c.speed_band_summary or _tr(plan.lang, "UNKNOWN"),
        w=content_w,
        max_lines=3,
    )
    total += _measure_section_block_height(
        appendix_c.phase_summary or _tr(plan.lang, "UNKNOWN"),
        w=content_w,
        max_lines=3,
    )
    if appendix_c.observations:
        observations_text = "\n".join(f"- {item}" for item in appendix_c.observations[:2])
        total += _measure_section_block_height(observations_text, w=content_w, max_lines=6)
    return float(max(34 * mm, total + 3 * mm))


def _estimate_appendix_c_suitability_panel_height(
    plan: AppendixCRenderPlan, *, width: float
) -> float:
    appendix_c = plan.appendix
    content_w = width - 8 * mm
    total = PANEL_HEADER_H + 2 * mm
    if appendix_c.limits_summary:
        total += (
            _measure_text_height(
                appendix_c.limits_summary,
                w=content_w,
                size=FS_SMALL,
                leading=FS_SMALL + 1.0,
                max_lines=4,
            )
            + 1.0 * mm
        )
    filtered_suitability_items = [
        item for item in appendix_c.suitability_items if item.detail != plan.action_status_note
    ]
    for item in filtered_suitability_items[:5]:
        total += (
            _measure_text_height(item.check, w=content_w, size=FS_SMALL, max_lines=1) + 0.4 * mm
        )
        if item.detail:
            total += (
                _measure_text_height(
                    item.detail,
                    w=content_w,
                    size=FS_SMALL,
                    leading=FS_SMALL + 1.0,
                    max_lines=2,
                )
                + 0.8 * mm
            )
    return float(max(34 * mm, total + 3 * mm))


def _estimate_appendix_c_trace_panel_height(plan: AppendixCRenderPlan, *, width: float) -> float:
    content_w = width - 8 * mm
    total = PANEL_HEADER_H + 2 * mm
    for row in plan.trace_rows:
        total += _estimate_appendix_c_traceability_row_height(row, width=content_w)
    return float(max(34 * mm, total + 3 * mm))


def _estimate_table_height(
    *,
    width: float,
    headers: list[str],
    rows: list[list[str]],
    col_widths: list[float],
    max_body_lines: int = 2,
) -> float:
    total_ratio = sum(col_widths)
    widths = [width * (ratio / total_ratio) for ratio in col_widths]
    header_lines = [
        _wrap_lines(header, width_part - 3 * mm, FS_SMALL)
        for width_part, header in zip(widths, headers, strict=False)
    ]
    header_line_count = max((len(lines) for lines in header_lines), default=1)
    header_h = max(8 * mm, (header_line_count * (FS_SMALL + 1.0)) + 3.5 * mm)
    total = header_h
    for row in rows:
        line_counts = [
            max(1, len(_wrap_lines(str(cell), width_part - 3 * mm, FS_SMALL)))
            for cell, width_part in zip(row, widths, strict=False)
        ]
        total += max(9 * mm, min(max_body_lines, max(line_counts)) * (FS_SMALL + 1.2) + 3.5 * mm)
    return float(total)


def _estimate_worksheet_top_panel_height(appendix: AppendixAData, *, lang: str) -> float:
    width = PAGE_W - 2 * MARGIN
    col_gap = 6 * mm
    left_col_w = (width - 8 * mm - col_gap) * 0.58
    right_col_w = width - 8 * mm - col_gap - left_col_w
    total = PANEL_HEADER_H + 2 * mm
    total += (
        _measure_text_height(
            _tr(lang, "REPORT_SOURCE_CONFIDENCE_NOTE"),
            w=width - 8 * mm,
            size=FS_SMALL,
            leading=FS_SMALL + 1.0,
            max_lines=2,
        )
        + 1.2 * mm
    )

    left_height = _measure_section_block_height(
        appendix.primary_source or _tr(lang, "UNKNOWN"),
        w=left_col_w,
        max_lines=2,
    )
    primary_inspect_first = (
        appendix.ranked_candidates[0].inspect_first if appendix.ranked_candidates else None
    )
    if primary_inspect_first:
        left_height += _measure_section_block_height(
            primary_inspect_first, w=left_col_w, max_lines=2
        )
    if appendix.why_primary_first:
        left_height += _measure_section_block_height(
            appendix.why_primary_first,
            w=left_col_w,
            max_lines=3,
        )

    right_height = 0.0
    if appendix.alternative_source:
        right_height += _measure_section_block_height(
            appendix.alternative_source,
            w=right_col_w,
            max_lines=2,
        )
    if appendix.why_alternative_next:
        right_height += _measure_section_block_height(
            appendix.why_alternative_next,
            w=right_col_w,
            max_lines=3,
        )
    if appendix.next_if_clean:
        right_height += _measure_section_block_height(
            appendix.next_if_clean,
            w=right_col_w,
            max_lines=3,
        )
    return float(min(56 * mm, max(42 * mm, total + max(left_height, right_height) + 3 * mm)))


def _estimate_worksheet_ranked_stack_height(appendix: AppendixAData, *, lang: str) -> float:
    if len(appendix.ranked_candidates) <= 2:
        return 0.0
    width = PAGE_W - 2 * MARGIN
    stack_rows = [
        [
            row.source_name,
            row.inspect_first or _tr(lang, "UNKNOWN"),
            row.path_role or _tr(lang, "UNKNOWN"),
            row.reason or "",
        ]
        for row in appendix.ranked_candidates
    ]
    table_height = _estimate_table_height(
        width=width - 8 * mm,
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
    return float(min(62 * mm, max(34 * mm, table_height + 17 * mm)))


def _worksheet_first_actions_panel_height(appendix: AppendixAData, *, lang: str) -> float:
    title_y = PAGE_H - MARGIN - (12 * mm) - GAP
    top_h = _estimate_worksheet_top_panel_height(appendix, lang=lang)
    top_y = title_y - top_h
    stack_h = _estimate_worksheet_ranked_stack_height(appendix, lang=lang)
    if stack_h > 0.0:
        stack_y = top_y - GAP - stack_h
        return float(stack_y - GAP - (MARGIN + 8 * mm))
    return float(top_y - GAP - (MARGIN + 8 * mm))


def _worksheet_continuation_panel_height() -> float:
    title_y = PAGE_H - MARGIN - (12 * mm) - GAP
    return float(title_y - (MARGIN + 8 * mm))


def _estimate_action_steps_panel_height(steps: list[NextStep], *, width: float) -> float:
    inner_w = width - 8 * mm
    gaps_h = max(len(steps) - 1, 0) * 2.5 * mm
    cards_h = sum(estimate_detailed_action_card_height(step, width=inner_w) for step in steps)
    return float(max(PANEL_HEADER_H + 12 * mm, PANEL_HEADER_H + 7 * mm + cards_h + gaps_h))


def _fit_action_steps(steps: list[NextStep], *, panel_w: float, panel_h: float) -> int:
    inner_w = panel_w - 8 * mm
    row_y = panel_h - PANEL_HEADER_H - 2 * mm
    count = 0
    for step in steps:
        estimated_h = estimate_detailed_action_card_height(step, width=inner_w)
        if row_y - estimated_h < 4 * mm:
            break
        row_y = row_y - estimated_h - 2.5 * mm
        count += 1
    return count
