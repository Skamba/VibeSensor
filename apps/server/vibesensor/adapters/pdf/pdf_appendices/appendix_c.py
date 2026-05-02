"""Appendix C page rendering."""

from __future__ import annotations

from typing import TYPE_CHECKING

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

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
    _measure_section_block_height,
)
from vibesensor.report_i18n import tr as _tr

from .layout import (
    _estimate_appendix_c_context_panel_height,
    _estimate_appendix_c_suitability_panel_height,
    _estimate_appendix_c_trace_panel_height,
)
from .tables import _draw_table, _draw_traceability_row, _fmt_db, _fmt_hz
from .title_bar import draw_appendix_title_bar

__all__ = ["_appendix_c_page"]

if TYPE_CHECKING:
    from vibesensor.adapters.pdf.report_types import AppendixCRenderPlan
    from vibesensor.shared.boundaries.reporting.document import AppendixCData


def _appendix_c_page(c: Canvas, plan: AppendixCRenderPlan) -> None:
    title_y = draw_appendix_title_bar(
        c,
        title=_tr(plan.lang, "REPORT_APPENDIX_C_TITLE"),
        width=PAGE_W - 2 * MARGIN,
        page_top=PAGE_H - MARGIN,
    )
    appendix = plan.appendix
    width = PAGE_W - 2 * MARGIN

    chain_h = _evidence_chain_panel_height(appendix)
    chain_y = title_y - chain_h
    _draw_panel(c, MARGIN, chain_y, width, chain_h, _tr(plan.lang, "REPORT_EVIDENCE_CHAIN_TITLE"))
    chain_top = (
        _draw_text(
            c,
            MARGIN + 4 * mm,
            chain_y + chain_h - PANEL_HEADER_H - 2 * mm,
            width - 8 * mm,
            appendix.evidence_summary or _tr(plan.lang, "REPORT_EVIDENCE_CHAIN_NOTE"),
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
        _tr(plan.lang, "REPORT_SOURCE_COLUMN"),
        _tr(plan.lang, "REPORT_SIGNAL_COLUMN"),
        _tr(plan.lang, "REPORT_MEASUREMENT_REFS_COLUMN"),
        _tr(plan.lang, "REPORT_MATCHED_WINDOWS_COLUMN"),
        _tr(plan.lang, "REPORT_SPEED_WINDOW_COLUMN"),
        _tr(plan.lang, "REPORT_LOCATION_COLUMN"),
    ]
    chain_widths = [0.18, 0.19, 0.15, 0.12, 0.16, 0.20]
    chain_rows = []
    for row in appendix.evidence_chain_rows:
        current = [
            row.source_name,
            row.supporting_signal_label,
            ", ".join(row.measurement_refs) or _tr(plan.lang, "REPORT_MEASUREMENT_REFS_NONE"),
            str(row.matched_evidence_window_count or 0),
            row.speed_window or _tr(plan.lang, "UNKNOWN"),
            row.dominant_location or _tr(plan.lang, "UNKNOWN"),
        ]
        if show_ambiguity:
            current.append(row.ambiguity_note or "—")
        chain_rows.append(current)
    if show_ambiguity:
        chain_headers.append(_tr(plan.lang, "REPORT_AMBIGUITY_COLUMN"))
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

    measurement_h = _measurement_panel_height(appendix)
    measurement_y = chain_y - GAP - measurement_h
    _draw_panel(
        c,
        MARGIN,
        measurement_y,
        width,
        measurement_h,
        _tr(
            plan.lang,
            "REPORT_SUPPORTING_WINDOWS_TITLE"
            if appendix.proof_window_rows
            else "REPORT_SUPPORTING_MEASUREMENTS_TITLE",
        ),
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
                    plan.lang,
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
    if appendix.proof_window_rows:
        measurement_headers = [
            _tr(plan.lang, "REPORT_WINDOW_ID_COLUMN"),
            _tr(plan.lang, "REPORT_TIME_COLUMN"),
            _tr(plan.lang, "REPORT_SPEED_COLUMN"),
            _tr(plan.lang, "FREQUENCY_HZ"),
            _tr(plan.lang, "REPORT_LOCATION_COLUMN"),
            _tr(plan.lang, "REPORT_PHASE_COLUMN"),
        ]
        measurement_rows = [
            [
                row.window_id,
                f"{row.time_s:.1f} s" if row.time_s is not None else _tr(plan.lang, "UNKNOWN"),
                (
                    f"{row.speed_kmh:.0f} km/h"
                    if row.speed_kmh is not None
                    else _tr(plan.lang, "UNKNOWN")
                ),
                _fmt_hz(row.matched_hz),
                row.dominant_location or _tr(plan.lang, "UNKNOWN"),
                row.phase or _tr(plan.lang, "UNKNOWN"),
            ]
            for row in appendix.proof_window_rows
        ]
        measurement_widths = [0.11, 0.14, 0.16, 0.18, 0.20, 0.21]
    elif shared_measurement_context:
        measurement_headers = [
            _tr(plan.lang, "REPORT_MEASUREMENT_ID_COLUMN"),
            _tr(plan.lang, "FREQUENCY_HZ"),
            _tr(plan.lang, "REPORT_PEAK_DB_COLUMN"),
            _tr(plan.lang, "REPORT_STRENGTH_DB_COLUMN"),
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
            _tr(plan.lang, "REPORT_MEASUREMENT_ID_COLUMN"),
            _tr(plan.lang, "REPORT_SOURCE_COLUMN"),
            _tr(plan.lang, "REPORT_SIGNAL_COLUMN"),
            _tr(plan.lang, "REPORT_PEAK_DB_COLUMN"),
            _tr(plan.lang, "REPORT_STRENGTH_DB_COLUMN"),
            _tr(plan.lang, "REPORT_SPEED_WINDOW_COLUMN"),
            _tr(plan.lang, "REPORT_LOCATION_COLUMN"),
        ]
        measurement_rows = [
            [
                row.measurement_id,
                row.source_name,
                row.signal_label,
                _fmt_db(row.peak_db),
                _fmt_db(row.strength_db),
                row.speed_window or _tr(plan.lang, "UNKNOWN"),
                row.dominant_location or _tr(plan.lang, "UNKNOWN"),
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

    context_w = width * 0.24
    suitability_w = width * 0.31
    trace_w = width - context_w - suitability_w - (2 * GAP)
    max_lower_h = measurement_y - GAP - (MARGIN + 8 * mm)
    lower_h = min(
        max_lower_h,
        max(
            _estimate_appendix_c_context_panel_height(plan, width=context_w),
            _estimate_appendix_c_suitability_panel_height(plan, width=suitability_w),
            _estimate_appendix_c_trace_panel_height(plan, width=trace_w),
        ),
    )
    lower_y = measurement_y - GAP - lower_h
    _draw_panel(
        c, MARGIN, lower_y, context_w, lower_h, _tr(plan.lang, "REPORT_SUPPORTING_CONTEXT_TITLE")
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
    for snapshot in appendix.evidence_snapshot_rows[:5]:
        block_y, did_draw = _draw_section_block_if_room(
            c,
            block_x,
            block_y,
            context_w - 8 * mm,
            snapshot.label,
            snapshot.value or _tr(plan.lang, "UNKNOWN"),
            bottom_y=lower_y + 4 * mm,
            max_lines=3,
        )
        if not did_draw:
            block_y = _draw_context_overflow_note(
                c,
                x=block_x,
                y=block_y,
                w=context_w - 8 * mm,
                bottom_y=lower_y + 4 * mm,
                lang=plan.lang,
            )
            break
    did_draw = True
    show_speed_phase = bool(appendix.speed_band_summary or appendix.phase_summary) or not bool(
        appendix.observations
    )
    if show_speed_phase:
        block_y, did_draw = _draw_section_block_if_room(
            c,
            block_x,
            block_y,
            context_w - 8 * mm,
            _tr(plan.lang, "REPORT_SPEED_BAND_SUMMARY_LABEL"),
            appendix.speed_band_summary or _tr(plan.lang, "UNKNOWN"),
            bottom_y=lower_y + 4 * mm,
            max_lines=3,
        )
        if did_draw:
            block_y, did_draw = _draw_section_block_if_room(
                c,
                block_x,
                block_y,
                context_w - 8 * mm,
                _tr(plan.lang, "REPORT_PHASE_SUMMARY_LABEL"),
                appendix.phase_summary or _tr(plan.lang, "UNKNOWN"),
                bottom_y=lower_y + 4 * mm,
                max_lines=3,
            )
    if not did_draw:
        block_y = _draw_context_overflow_note(
            c,
            x=block_x,
            y=block_y,
            w=context_w - 8 * mm,
            bottom_y=lower_y + 4 * mm,
            lang=plan.lang,
        )
    if appendix.observations and block_y > lower_y + 8 * mm:
        observations_text = "\n".join(f"- {item}" for item in appendix.observations[:2])
        block_y, did_draw = _draw_section_block_if_room(
            c,
            block_x,
            block_y,
            context_w - 8 * mm,
            _tr(plan.lang, "ADDITIONAL_OBSERVATIONS"),
            observations_text,
            bottom_y=lower_y + 4 * mm,
            max_lines=4,
        )
        if not did_draw:
            _draw_context_overflow_note(
                c,
                x=block_x,
                y=block_y,
                w=context_w - 8 * mm,
                bottom_y=lower_y + 4 * mm,
                lang=plan.lang,
            )

    suitability_x = MARGIN + context_w + GAP
    _draw_panel(
        c,
        suitability_x,
        lower_y,
        suitability_w,
        lower_h,
        _tr(plan.lang, "REPORT_SUITABILITY_DETAIL_TITLE"),
    )
    trust_x = suitability_x + 4 * mm
    trust_y = lower_y + lower_h - PANEL_HEADER_H - 2 * mm
    filtered_suitability_items = [
        item for item in appendix.suitability_items if item.detail != plan.action_status_note
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
        c, trace_x, lower_y, trace_w, lower_h, _tr(plan.lang, "REPORT_TRACEABILITY_PANEL_TITLE")
    )
    trace_y = lower_y + lower_h - PANEL_HEADER_H - 2 * mm
    for trace_row in plan.trace_rows:
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


def _draw_section_block_if_room(
    c: Canvas,
    x: float,
    y: float,
    w: float,
    title: str,
    body: str,
    *,
    bottom_y: float,
    max_lines: int,
) -> tuple[float, bool]:
    needed_h = _measure_section_block_height(body, w=w, max_lines=max_lines)
    if y - needed_h < bottom_y:
        return y, False
    return (
        _draw_section_block(
            c,
            x,
            y,
            w,
            title,
            body,
            max_lines=max_lines,
        ),
        True,
    )


def _draw_context_overflow_note(
    c: Canvas,
    *,
    x: float,
    y: float,
    w: float,
    bottom_y: float,
    lang: str,
) -> float:
    if y - 6 * mm < bottom_y:
        return y
    return float(
        _draw_text(
            c,
            x,
            y,
            w,
            _tr(lang, "REPORT_CONTEXT_MORE_NOT_SHOWN"),
            size=FS_SMALL,
            color=SUB_CLR,
            leading=FS_SMALL + 1.0,
            max_lines=2,
        )
        - 0.8 * mm
    )


def _evidence_chain_panel_height(appendix: AppendixCData) -> float:
    row_count = len(appendix.evidence_chain_rows)
    extra_rows = max(0, row_count - 3)
    return float(min(76 * mm, 58 * mm + (extra_rows * 12 * mm)))


def _measurement_panel_height(appendix: AppendixCData) -> float:
    proof_window_count = len(appendix.proof_window_rows)
    if proof_window_count:
        extra_rows = max(0, proof_window_count - 4)
        return float(min(98 * mm, 72 * mm + (extra_rows * 12 * mm)))
    measurement_count = len(appendix.measurement_rows)
    extra_rows = max(0, measurement_count - 4)
    return float(min(92 * mm, 72 * mm + (extra_rows * 10 * mm)))
