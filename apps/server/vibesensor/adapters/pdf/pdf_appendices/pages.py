"""Appendix B/C/D page rendering."""

from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.panels._panel_title_bar import _draw_title_bar
from vibesensor.adapters.pdf.pdf_diagram_render import car_location_diagram
from vibesensor.adapters.pdf.pdf_drawing import _draw_panel
from vibesensor.adapters.pdf.pdf_style import (
    FONT_B,
    FS_SMALL,
    GAP,
    MARGIN,
    PAGE_H,
    PAGE_W,
    PANEL_HEADER_H,
    SUB_CLR,
    TEXT_CLR,
)
from vibesensor.adapters.pdf.pdf_text import (
    _draw_section_block,
    _draw_text,
)
from vibesensor.adapters.pdf.report_data import (
    AppendixBData,
    ReportTemplateData,
)
from vibesensor.report_i18n import tr as _tr

from .layout import (
    _estimate_appendix_c_context_panel_height,
    _estimate_appendix_c_suitability_panel_height,
    _estimate_appendix_c_trace_panel_height,
)
from .tables import _draw_table, _draw_traceability_row, _fmt_db, _fmt_hz, _fmt_relative_db

__all__ = [
    "_appendix_b_page",
    "_appendix_c_page",
    "_appendix_d_page",
    "_has_appendix_b_content",
]


def _appendix_b_page(c: Canvas, data: ReportTemplateData) -> None:
    title_y = _draw_title_bar(
        c,
        title=_tr(data.lang, "REPORT_APPENDIX_B_TITLE"),
        width=PAGE_W - 2 * MARGIN,
        page_top=PAGE_H - MARGIN,
    )
    appendix = data.appendix_b
    width = PAGE_W - 2 * MARGIN
    top_h = 114 * mm
    left_w = width * 0.56
    right_w = width - left_w - GAP
    top_y = title_y - top_h

    _draw_panel(c, MARGIN, top_y, left_w, top_h, _tr(data.lang, "REPORT_TOPOLOGY_MAP_TITLE"))
    _draw_text(
        c,
        MARGIN + 4 * mm,
        top_y + top_h - PANEL_HEADER_H - 2 * mm,
        left_w - 8 * mm,
        _tr(data.lang, "REPORT_TOPOLOGY_MAP_NOTE"),
        size=FS_SMALL,
        color=SUB_CLR,
        leading=FS_SMALL + 1.0,
        max_lines=1,
    )
    diagram = car_location_diagram(
        data.top_causes or data.findings,
        {
            "sensor_locations": data.sensor_locations,
            "sensor_intensity_by_location": data.sensor_intensity_by_location,
        },
        data.location_hotspot_rows,
        content_width=left_w - 8 * mm,
        tr=lambda key, **kw: _tr(data.lang, key, **kw),
        text_fn=lambda en, nl: nl if data.lang == "nl" else en,
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
        _tr(data.lang, "REPORT_DOMINANCE_SUMMARY_TITLE"),
    )
    text_x = MARGIN + left_w + GAP + 4 * mm
    text_y = top_y + top_h - PANEL_HEADER_H - 2 * mm
    text_y = _draw_section_block(
        c,
        text_x,
        text_y,
        right_w - 8 * mm,
        _tr(data.lang, "REPORT_DOMINANT_CORNER_LABEL"),
        appendix.dominant_corner or _tr(data.lang, "UNKNOWN"),
    )
    if appendix.runner_up_corner:
        text_y = _draw_section_block(
            c,
            text_x,
            text_y,
            right_w - 8 * mm,
            _tr(data.lang, "REPORT_RUNNER_UP_CORNER_LABEL"),
            appendix.runner_up_corner,
        )
    text_y = _draw_section_block(
        c,
        text_x,
        text_y,
        right_w - 8 * mm,
        _tr(data.lang, "REPORT_DOMINANCE_RATIO_LABEL"),
        appendix.dominance_ratio_text or _tr(data.lang, "UNKNOWN"),
    )
    if appendix.dominance_ratio_text:
        text_y = (
            _draw_text(
                c,
                text_x,
                text_y,
                right_w - 8 * mm,
                _tr(data.lang, "REPORT_DOMINANCE_RATIO_NOTE"),
                size=FS_SMALL,
                color=SUB_CLR,
                leading=FS_SMALL + 1.0,
                max_lines=4,
            )
            - 0.8 * mm
        )
    text_y = _draw_section_block(
        c,
        text_x,
        text_y,
        right_w - 8 * mm,
        _tr(data.lang, "REPORT_LOCATION_CONFIDENCE_LABEL"),
        appendix.location_confidence or _tr(data.lang, "UNKNOWN"),
    )
    text_y = _draw_section_block(
        c,
        text_x,
        text_y,
        right_w - 8 * mm,
        _tr(data.lang, "REPORT_COVERAGE_LABEL"),
        appendix.coverage_label or _tr(data.lang, "UNKNOWN"),
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

    bottom_h = top_y - (MARGIN + 8 * mm)
    bottom_y = MARGIN + 8 * mm
    if appendix.sensor_observation_rows:
        _draw_panel(
            c,
            MARGIN,
            bottom_y,
            width,
            bottom_h,
            _tr(data.lang, "REPORT_SENSOR_OBSERVATION_MATRIX_TITLE"),
        )
        table_top = (
            _draw_text(
                c,
                MARGIN + 4 * mm,
                bottom_y + bottom_h - 13 * mm,
                width - 8 * mm,
                _tr(data.lang, "REPORT_SENSOR_OBSERVATION_MATRIX_NOTE"),
                size=FS_SMALL,
                color=SUB_CLR,
                leading=FS_SMALL + 1.0,
                max_lines=3,
            )
            - 1.2 * mm
        )
        headers = [_tr(data.lang, "REPORT_SIGNAL_COLUMN")] + [
            cell.location for cell in appendix.sensor_observation_rows[0].sensor_levels
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
            y_bottom=bottom_y + 4 * mm,
            headers=headers,
            rows=rows,
            col_widths=[0.32] + ([0.68 / sensor_column_count] * sensor_column_count),
            max_body_lines=3,
        )
    else:
        _draw_panel(
            c, MARGIN, bottom_y, width, bottom_h, _tr(data.lang, "REPORT_INTENSITY_LADDER_TITLE")
        )
        rows = [
            [row.location, _fmt_db(row.p95_db), row.coverage_state or _tr(data.lang, "UNKNOWN")]
            for row in appendix.intensity_rows
        ]
        _draw_table(
            c,
            x=MARGIN + 4 * mm,
            y=bottom_y + bottom_h - 13 * mm,
            w=width - 8 * mm,
            y_bottom=bottom_y + 4 * mm,
            headers=[
                _tr(data.lang, "REPORT_LOCATION_COLUMN"),
                _tr(data.lang, "REPORT_P95_DB_COLUMN"),
                _tr(data.lang, "REPORT_COVERAGE_STATE_COLUMN"),
            ],
            rows=rows,
            col_widths=[0.42, 0.18, 0.40],
        )


def _has_appendix_b_content(appendix: AppendixBData) -> bool:
    return any(
        (
            appendix.dominant_corner,
            appendix.runner_up_corner,
            appendix.dominance_ratio_text,
            appendix.location_confidence,
            appendix.coverage_label,
            appendix.coverage_notes,
            appendix.intensity_rows,
            appendix.sensor_observation_rows,
        )
    )


def _appendix_c_page(c: Canvas, data: ReportTemplateData) -> None:
    title_y = _draw_title_bar(
        c,
        title=_tr(data.lang, "REPORT_APPENDIX_C_TITLE"),
        width=PAGE_W - 2 * MARGIN,
        page_top=PAGE_H - MARGIN,
    )
    appendix = data.appendix_c
    appendix_d = data.appendix_d
    width = PAGE_W - 2 * MARGIN

    chain_h = 58 * mm
    chain_y = title_y - chain_h
    _draw_panel(c, MARGIN, chain_y, width, chain_h, _tr(data.lang, "REPORT_EVIDENCE_CHAIN_TITLE"))
    chain_top = (
        _draw_text(
            c,
            MARGIN + 4 * mm,
            chain_y + chain_h - PANEL_HEADER_H - 2 * mm,
            width - 8 * mm,
            appendix.evidence_summary or _tr(data.lang, "REPORT_EVIDENCE_CHAIN_NOTE"),
            size=FS_SMALL,
            color=SUB_CLR,
            leading=FS_SMALL + 1.0,
            max_lines=3,
        )
        - 1.0 * mm
    )
    show_ambiguity = len(appendix.evidence_chain_rows) > 1 and any(
        bool(row.ambiguity_note) for row in appendix.evidence_chain_rows
    )
    chain_headers = [
        _tr(data.lang, "REPORT_SOURCE_COLUMN"),
        _tr(data.lang, "REPORT_SIGNAL_COLUMN"),
        _tr(data.lang, "REPORT_MEASUREMENT_REFS_COLUMN"),
        _tr(data.lang, "REPORT_MATCHED_WINDOWS_COLUMN"),
        _tr(data.lang, "REPORT_SPEED_WINDOW_COLUMN"),
        _tr(data.lang, "REPORT_LOCATION_COLUMN"),
    ]
    chain_widths = [0.18, 0.19, 0.15, 0.12, 0.16, 0.20]
    chain_rows = []
    for row in appendix.evidence_chain_rows:
        current = [
            row.source_name,
            row.supporting_signal_label,
            ", ".join(row.measurement_refs) or _tr(data.lang, "REPORT_MEASUREMENT_REFS_NONE"),
            str(row.matched_evidence_window_count or 0),
            row.speed_window or _tr(data.lang, "UNKNOWN"),
            row.dominant_location or _tr(data.lang, "UNKNOWN"),
        ]
        if show_ambiguity:
            current.append(row.ambiguity_note or "—")
        chain_rows.append(current)
    if show_ambiguity:
        chain_headers.append(_tr(data.lang, "REPORT_AMBIGUITY_COLUMN"))
        chain_widths = [0.15, 0.16, 0.13, 0.10, 0.13, 0.11, 0.22]
    _draw_table(
        c,
        x=MARGIN + 4 * mm,
        y=chain_top,
        w=width - 8 * mm,
        y_bottom=chain_y + 4 * mm,
        headers=chain_headers,
        rows=chain_rows,
        col_widths=chain_widths,
        max_body_lines=2,
    )

    measurement_h = 72 * mm
    measurement_y = chain_y - GAP - measurement_h
    _draw_panel(
        c,
        MARGIN,
        measurement_y,
        width,
        measurement_h,
        _tr(data.lang, "REPORT_SUPPORTING_MEASUREMENTS_TITLE"),
    )
    measurement_source_values = {
        row.source_name for row in appendix.measurement_rows if row.source_name
    }
    measurement_signal_values = {
        row.signal_label for row in appendix.measurement_rows if row.signal_label
    }
    measurement_speed_values = {
        row.speed_window for row in appendix.measurement_rows if row.speed_window
    }
    measurement_location_values = {
        row.dominant_location for row in appendix.measurement_rows if row.dominant_location
    }
    shared_measurement_context = (
        len(measurement_source_values) == 1
        and len(measurement_signal_values) == 1
        and len(measurement_speed_values) == 1
        and len(measurement_location_values) == 1
    )
    measurement_top = measurement_y + measurement_h - PANEL_HEADER_H - 2 * mm
    if shared_measurement_context:
        measurement_top = (
            _draw_text(
                c,
                MARGIN + 4 * mm,
                measurement_top,
                width - 8 * mm,
                _tr(
                    data.lang,
                    "REPORT_SUPPORTING_MEASUREMENTS_SHARED_CONTEXT",
                    source=next(iter(measurement_source_values)),
                    signal=next(iter(measurement_signal_values)),
                    speed=next(iter(measurement_speed_values)),
                    location=next(iter(measurement_location_values)),
                ),
                size=FS_SMALL,
                color=TEXT_CLR,
                leading=FS_SMALL + 1.0,
                max_lines=1,
            )
            - 0.8 * mm
        )
    if appendix.measurement_guide:
        measurement_top = (
            _draw_text(
                c,
                MARGIN + 4 * mm,
                measurement_top,
                width - 8 * mm,
                appendix.measurement_guide,
                size=FS_SMALL,
                color=SUB_CLR,
                leading=FS_SMALL + 1.0,
                max_lines=2,
            )
            - 0.8 * mm
        )
    if shared_measurement_context:
        measurement_headers = [
            _tr(data.lang, "REPORT_MEASUREMENT_ID_COLUMN"),
            _tr(data.lang, "FREQUENCY_HZ"),
            _tr(data.lang, "REPORT_PEAK_DB_COLUMN"),
            _tr(data.lang, "REPORT_STRENGTH_DB_COLUMN"),
        ]
        measurement_rows = [
            [
                row.measurement_id,
                _fmt_hz(row.frequency_hz),
                _fmt_db(row.peak_db),
                _fmt_db(row.strength_db),
            ]
            for row in appendix.measurement_rows
        ]
        measurement_widths = [0.18, 0.22, 0.30, 0.30]
    else:
        measurement_headers = [
            _tr(data.lang, "REPORT_MEASUREMENT_ID_COLUMN"),
            _tr(data.lang, "REPORT_SOURCE_COLUMN"),
            _tr(data.lang, "REPORT_SIGNAL_COLUMN"),
            _tr(data.lang, "REPORT_PEAK_DB_COLUMN"),
            _tr(data.lang, "REPORT_STRENGTH_DB_COLUMN"),
            _tr(data.lang, "REPORT_SPEED_WINDOW_COLUMN"),
            _tr(data.lang, "REPORT_LOCATION_COLUMN"),
        ]
        measurement_rows = [
            [
                row.measurement_id,
                row.source_name,
                row.signal_label,
                _fmt_db(row.peak_db),
                _fmt_db(row.strength_db),
                row.speed_window or _tr(data.lang, "UNKNOWN"),
                row.dominant_location or _tr(data.lang, "UNKNOWN"),
            ]
            for row in appendix.measurement_rows
        ]
        measurement_widths = [0.10, 0.16, 0.18, 0.10, 0.10, 0.17, 0.19]
    _draw_table(
        c,
        x=MARGIN + 4 * mm,
        y=measurement_top,
        w=width - 8 * mm,
        y_bottom=measurement_y + 4 * mm,
        headers=measurement_headers,
        rows=measurement_rows,
        col_widths=measurement_widths,
        max_body_lines=2,
    )

    context_w = width * 0.24
    suitability_w = width * 0.31
    trace_w = width - context_w - suitability_w - (2 * GAP)
    max_lower_h = measurement_y - GAP - (MARGIN + 8 * mm)
    lower_h = min(
        max_lower_h,
        max(
            _estimate_appendix_c_context_panel_height(data, width=context_w),
            _estimate_appendix_c_suitability_panel_height(data, width=suitability_w),
            _estimate_appendix_c_trace_panel_height(data, width=trace_w),
        ),
    )
    lower_y = measurement_y - GAP - lower_h
    _draw_panel(
        c, MARGIN, lower_y, context_w, lower_h, _tr(data.lang, "REPORT_SUPPORTING_CONTEXT_TITLE")
    )
    block_x = MARGIN + 4 * mm
    block_y = lower_y + lower_h - PANEL_HEADER_H - 2 * mm
    if appendix.context_summary:
        block_y = (
            _draw_text(
                c,
                block_x,
                block_y,
                context_w - 8 * mm,
                appendix.context_summary,
                size=FS_SMALL,
                color=SUB_CLR,
                leading=FS_SMALL + 1.0,
                max_lines=4,
            )
            - 1.2 * mm
        )
    block_y = _draw_section_block(
        c,
        block_x,
        block_y,
        context_w - 8 * mm,
        _tr(data.lang, "REPORT_SPEED_BAND_SUMMARY_LABEL"),
        appendix.speed_band_summary or _tr(data.lang, "UNKNOWN"),
        max_lines=3,
    )
    block_y = _draw_section_block(
        c,
        block_x,
        block_y,
        context_w - 8 * mm,
        _tr(data.lang, "REPORT_PHASE_SUMMARY_LABEL"),
        appendix.phase_summary or _tr(data.lang, "UNKNOWN"),
        max_lines=3,
    )
    if appendix.observations:
        observations_text = "\n".join(f"- {item}" for item in appendix.observations[:2])
        _draw_section_block(
            c,
            block_x,
            block_y,
            context_w - 8 * mm,
            _tr(data.lang, "ADDITIONAL_OBSERVATIONS"),
            observations_text,
            max_lines=6,
        )

    suitability_x = MARGIN + context_w + GAP
    _draw_panel(
        c,
        suitability_x,
        lower_y,
        suitability_w,
        lower_h,
        _tr(data.lang, "REPORT_SUITABILITY_DETAIL_TITLE"),
    )
    trust_x = suitability_x + 4 * mm
    trust_y = lower_y + lower_h - PANEL_HEADER_H - 2 * mm
    filtered_suitability_items = [
        item
        for item in appendix.suitability_items
        if item.detail != data.verdict_page.action_status_note
    ]
    if appendix.limits_summary:
        trust_y = (
            _draw_text(
                c,
                trust_x,
                trust_y,
                suitability_w - 8 * mm,
                appendix.limits_summary,
                size=FS_SMALL,
                color=SUB_CLR,
                leading=FS_SMALL + 1.0,
                max_lines=4,
            )
            - 1.0 * mm
        )
    for item in filtered_suitability_items[:5]:
        trust_y = (
            _draw_text(
                c,
                trust_x,
                trust_y,
                suitability_w - 8 * mm,
                item.check,
                font=FONT_B,
                size=FS_SMALL,
                color=TEXT_CLR if item.state == "pass" else SUB_CLR,
                leading=FS_SMALL + 1.0,
                max_lines=1,
            )
            - 0.4 * mm
        )
        if item.detail:
            trust_y = (
                _draw_text(
                    c,
                    trust_x,
                    trust_y,
                    suitability_w - 8 * mm,
                    item.detail,
                    size=FS_SMALL,
                    color=SUB_CLR,
                    leading=FS_SMALL + 1.0,
                    max_lines=2,
                )
                - 0.8 * mm
            )

    trace_x = suitability_x + suitability_w + GAP
    _draw_panel(
        c, trace_x, lower_y, trace_w, lower_h, _tr(data.lang, "REPORT_TRACEABILITY_PANEL_TITLE")
    )
    trace_y = lower_y + lower_h - PANEL_HEADER_H - 2 * mm
    for trace_row in appendix_d.rows:
        trace_y = (
            _draw_traceability_row(
                c,
                trace_row,
                x=trace_x + 4 * mm,
                y=trace_y,
                w=trace_w - 8 * mm,
            )
            - 0.4 * mm
        )
        if trace_y < lower_y + 4 * mm:
            break


def _appendix_d_page(c: Canvas, data: ReportTemplateData) -> None:
    title_y = _draw_title_bar(
        c,
        title=_tr(data.lang, "REPORT_APPENDIX_D_TITLE"),
        width=PAGE_W - 2 * MARGIN,
        page_top=PAGE_H - MARGIN,
    )
    appendix = data.appendix_d
    width = PAGE_W - 2 * MARGIN
    panel_h = title_y - (MARGIN + 8 * mm)
    panel_y = MARGIN + 8 * mm
    _draw_panel(
        c, MARGIN, panel_y, width, panel_h, _tr(data.lang, "REPORT_TRACEABILITY_PANEL_TITLE")
    )
    left_x = MARGIN + 4 * mm
    right_x = MARGIN + (width / 2) + 2 * mm
    left_y = panel_y + panel_h - PANEL_HEADER_H - 2 * mm
    right_y = left_y
    mid = (len(appendix.rows) + 1) // 2
    for row in appendix.rows[:mid]:
        left_y = (
            _draw_traceability_row(c, row, x=left_x, y=left_y, w=(width / 2) - 8 * mm) - 1.0 * mm
        )
    for row in appendix.rows[mid:]:
        right_y = (
            _draw_traceability_row(c, row, x=right_x, y=right_y, w=(width / 2) - 8 * mm) - 1.0 * mm
        )
