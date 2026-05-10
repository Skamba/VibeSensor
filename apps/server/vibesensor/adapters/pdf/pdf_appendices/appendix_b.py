"""Appendix B page rendering."""

from __future__ import annotations

from typing import TYPE_CHECKING

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.pdf_diagram_render import car_location_diagram
from vibesensor.adapters.pdf.pdf_drawing import _draw_panel, _hex
from vibesensor.adapters.pdf.pdf_style import (
    FONT_B,
    FS_SMALL,
    GAP,
    MARGIN,
    PAGE_H,
    PAGE_W,
    PANEL_HEADER_H,
    SUB_CLR,
)
from vibesensor.adapters.pdf.pdf_text import _draw_section_block, _draw_text
from vibesensor.report_i18n import human_location
from vibesensor.report_i18n import tr as _tr
from vibesensor.shared.boundaries.reporting.document import AppendixBData

from .tables import _draw_table, _fmt_db, _fmt_relative_db
from .title_bar import draw_appendix_title_bar

__all__ = [
    "_appendix_b_page",
    "_has_appendix_b_content",
]

if TYPE_CHECKING:
    from vibesensor.adapters.pdf.report_types import AppendixBRenderPlan


def _appendix_b_page(c: Canvas, plan: AppendixBRenderPlan) -> None:
    title_y = draw_appendix_title_bar(
        c,
        title=_tr(plan.lang, "REPORT_APPENDIX_B_TITLE"),
        width=PAGE_W - 2 * MARGIN,
        page_top=PAGE_H - MARGIN,
    )
    appendix = plan.appendix
    width = PAGE_W - 2 * MARGIN
    top_y = _draw_appendix_b_top_panels(c, plan=plan, title_y=title_y, width=width)
    _draw_appendix_b_bottom_panel(c, plan=plan, appendix=appendix, top_y=top_y, width=width)


def _draw_appendix_b_top_panels(
    c: Canvas,
    *,
    plan: AppendixBRenderPlan,
    title_y: float,
    width: float,
) -> float:
    appendix = plan.appendix
    top_h = 114 * mm
    left_w = width * 0.56
    right_w = width - left_w - GAP
    top_y = title_y - top_h

    _draw_panel(c, MARGIN, top_y, left_w, top_h, _tr(plan.lang, "REPORT_TOPOLOGY_MAP_TITLE"))
    _draw_text(
        c,
        MARGIN + 4 * mm,
        top_y + top_h - PANEL_HEADER_H - 2 * mm,
        left_w - 8 * mm,
        _tr(plan.lang, "REPORT_TOPOLOGY_MAP_NOTE"),
        size=FS_SMALL,
        color=SUB_CLR,
        leading=FS_SMALL + 1.0,
        max_lines=1,
    )
    diagram = car_location_diagram(
        plan.top_causes or plan.findings,
        {
            "sensor_locations": plan.sensor_locations,
            "sensor_intensity_by_location": plan.proof_sensor_intensity_by_location,
        },
        plan.proof_location_hotspot_rows,
        content_width=left_w - 8 * mm,
        tr=lambda key, **kw: _tr(plan.lang, key, **kw),
        diagram_width=left_w - 12 * mm,
        diagram_height=top_h - 24 * mm,
    )
    diagram.drawOn(c, MARGIN + 4 * mm, top_y + 6 * mm)

    _draw_panel(
        c,
        MARGIN + left_w + GAP,
        top_y,
        right_w,
        top_h,
        _tr(plan.lang, "REPORT_DOMINANCE_SUMMARY_TITLE"),
    )
    text_x = MARGIN + left_w + GAP + 4 * mm
    text_y = top_y + top_h - PANEL_HEADER_H - 2 * mm
    text_y = _draw_section_block(
        c,
        text_x,
        text_y,
        right_w - 8 * mm,
        _tr(plan.lang, "REPORT_DOMINANT_CORNER_LABEL"),
        human_location(appendix.dominant_corner, lang=plan.lang)
        if appendix.dominant_corner
        else _tr(plan.lang, "UNKNOWN"),
    )
    if appendix.runner_up_corner:
        text_y = _draw_section_block(
            c,
            text_x,
            text_y,
            right_w - 8 * mm,
            _tr(plan.lang, "REPORT_RUNNER_UP_CORNER_LABEL"),
            human_location(appendix.runner_up_corner, lang=plan.lang),
        )
    text_y = _draw_section_block(
        c,
        text_x,
        text_y,
        right_w - 8 * mm,
        _tr(plan.lang, "REPORT_DOMINANCE_RATIO_LABEL"),
        appendix.dominance_ratio_text or _tr(plan.lang, "UNKNOWN"),
    )
    if appendix.dominance_ratio_text:
        text_y = (
            _draw_text(
                c,
                text_x,
                text_y,
                right_w - 8 * mm,
                _tr(plan.lang, "REPORT_DOMINANCE_RATIO_NOTE"),
                size=FS_SMALL,
                color=SUB_CLR,
                leading=FS_SMALL + 1.0,
                max_lines=4,
            )
            - 0.8 * mm
        )
    if appendix.proof_basis_note:
        text_y = (
            _draw_text(
                c,
                text_x,
                text_y,
                right_w - 8 * mm,
                appendix.proof_basis_note,
                size=FS_SMALL,
                color=SUB_CLR,
                leading=FS_SMALL + 1.0,
                max_lines=3,
            )
            - 0.8 * mm
        )
    text_y = _draw_section_block(
        c,
        text_x,
        text_y,
        right_w - 8 * mm,
        _tr(plan.lang, "REPORT_LOCATION_CONFIDENCE_LABEL"),
        appendix.location_confidence or _tr(plan.lang, "UNKNOWN"),
    )
    text_y = _draw_section_block(
        c,
        text_x,
        text_y,
        right_w - 8 * mm,
        _tr(plan.lang, "REPORT_COVERAGE_LABEL"),
        appendix.coverage_label or _tr(plan.lang, "UNKNOWN"),
        max_lines=3,
    )
    for note in appendix.coverage_notes[:3]:
        text_y = (
            _draw_text(
                c,
                text_x,
                text_y,
                right_w - 8 * mm,
                note,
                size=FS_SMALL,
                color=SUB_CLR,
                leading=FS_SMALL + 1.2,
                max_lines=3,
            )
            - 1.0 * mm
        )
    return float(top_y)


def _draw_appendix_b_bottom_panel(
    c: Canvas,
    *,
    plan: AppendixBRenderPlan,
    appendix: AppendixBData,
    top_y: float,
    width: float,
) -> None:
    bottom_h = top_y - (MARGIN + 8 * mm)
    bottom_y = MARGIN + 8 * mm
    if appendix.sensor_observation_rows:
        _draw_panel(
            c,
            MARGIN,
            bottom_y,
            width,
            bottom_h,
            _tr(plan.lang, "REPORT_SENSOR_OBSERVATION_MATRIX_TITLE"),
        )
        table_top = (
            _draw_text(
                c,
                MARGIN + 4 * mm,
                bottom_y + bottom_h - 13 * mm,
                width - 8 * mm,
                _tr(plan.lang, "REPORT_SENSOR_OBSERVATION_MATRIX_NOTE"),
                size=FS_SMALL,
                color=SUB_CLR,
                leading=FS_SMALL + 1.0,
                max_lines=3,
            )
            - 1.2 * mm
        )
        show_intensity_snapshot = bool(appendix.intensity_rows) and bottom_h > 95 * mm
        matrix_bottom = bottom_y + (58 * mm if show_intensity_snapshot else 4 * mm)
        headers = [_tr(plan.lang, "REPORT_SIGNAL_COLUMN")] + [
            human_location(cell.location, lang=plan.lang)
            for cell in appendix.sensor_observation_rows[0].sensor_levels
        ]
        sensor_column_count = max(1, len(headers) - 1)
        rows = [
            [
                f"{row.source_name}\n{row.signal_label}",
                *[_fmt_relative_db(cell.relative_level_db) for cell in row.sensor_levels],
            ]
            for row in appendix.sensor_observation_rows
        ]
        _draw_table(
            c,
            x=MARGIN + 4 * mm,
            y=table_top,
            w=width - 8 * mm,
            y_bottom=matrix_bottom,
            headers=headers,
            rows=rows,
            col_widths=[0.32] + ([0.68 / sensor_column_count] * sensor_column_count),
            max_body_lines=3,
            overflow_text_template=_tr(
                plan.lang,
                "REPORT_TABLE_MORE_ROWS_NOT_SHOWN",
                count="{count}",
            ),
            overflow_singular_text_template=_tr(
                plan.lang,
                "REPORT_TABLE_MORE_ROW_NOT_SHOWN",
                count="{count}",
            ),
        )
        if show_intensity_snapshot:
            snapshot_title_y = matrix_bottom - 5 * mm
            c.setFillColor(_hex(SUB_CLR))
            c.setFont(FONT_B, FS_SMALL)
            c.drawString(
                MARGIN + 4 * mm, snapshot_title_y, _tr(plan.lang, "REPORT_INTENSITY_LADDER_TITLE")
            )
            intensity_rows = [
                [
                    human_location(row.location, lang=plan.lang),
                    _fmt_db(row.p95_db),
                    row.coverage_state or _tr(plan.lang, "UNKNOWN"),
                ]
                for row in appendix.intensity_rows
            ]
            _draw_table(
                c,
                x=MARGIN + 4 * mm,
                y=snapshot_title_y - 4.0 * mm,
                w=width - 8 * mm,
                y_bottom=bottom_y + 4 * mm,
                headers=[
                    _tr(plan.lang, "REPORT_LOCATION_COLUMN"),
                    _tr(plan.lang, "REPORT_P95_DB_COLUMN"),
                    _tr(plan.lang, "REPORT_COVERAGE_STATE_COLUMN"),
                ],
                rows=intensity_rows,
                col_widths=[0.42, 0.18, 0.40],
                overflow_text_template=_tr(
                    plan.lang,
                    "REPORT_TABLE_MORE_ROWS_NOT_SHOWN",
                    count="{count}",
                ),
                overflow_singular_text_template=_tr(
                    plan.lang,
                    "REPORT_TABLE_MORE_ROW_NOT_SHOWN",
                    count="{count}",
                ),
            )
    else:
        _draw_panel(
            c, MARGIN, bottom_y, width, bottom_h, _tr(plan.lang, "REPORT_INTENSITY_LADDER_TITLE")
        )
        rows = [
            [
                human_location(row.location, lang=plan.lang),
                _fmt_db(row.p95_db),
                row.coverage_state or _tr(plan.lang, "UNKNOWN"),
            ]
            for row in appendix.intensity_rows
        ]
        _draw_table(
            c,
            x=MARGIN + 4 * mm,
            y=bottom_y + bottom_h - 13 * mm,
            w=width - 8 * mm,
            y_bottom=bottom_y + 4 * mm,
            headers=[
                _tr(plan.lang, "REPORT_LOCATION_COLUMN"),
                _tr(plan.lang, "REPORT_P95_DB_COLUMN"),
                _tr(plan.lang, "REPORT_COVERAGE_STATE_COLUMN"),
            ],
            rows=rows,
            col_widths=[0.42, 0.18, 0.40],
            overflow_text_template=_tr(
                plan.lang,
                "REPORT_TABLE_MORE_ROWS_NOT_SHOWN",
                count="{count}",
            ),
            overflow_singular_text_template=_tr(
                plan.lang,
                "REPORT_TABLE_MORE_ROW_NOT_SHOWN",
                count="{count}",
            ),
        )


def _has_appendix_b_content(appendix: AppendixBData) -> bool:
    return any(
        (
            appendix.dominant_corner,
            appendix.runner_up_corner,
            appendix.dominance_ratio_text,
            appendix.proof_basis_note,
            appendix.location_confidence,
            appendix.coverage_label,
            appendix.coverage_notes,
            appendix.intensity_rows,
            appendix.sensor_observation_rows,
        )
    )
