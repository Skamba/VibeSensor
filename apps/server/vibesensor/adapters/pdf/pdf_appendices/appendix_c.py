"""Appendix C page rendering."""

from __future__ import annotations

from typing import TYPE_CHECKING

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.layout_primitives import (
    PanelRegion,
    draw_overflow_note_if_room,
    draw_panel_region,
    draw_section_block_if_room,
    draw_text_block,
)
from vibesensor.adapters.pdf.pdf_style import (
    FONT,
    FONT_B,
    FS_SMALL,
    GAP,
    MARGIN,
    PAGE_H,
    PAGE_W,
    REPORT_COLORS,
    SUB_CLR,
    TEXT_CLR,
)
from vibesensor.adapters.pdf.pdf_text import (
    _draw_text,
)
from vibesensor.report_i18n import human_location
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
    from vibesensor.shared.boundaries.reporting.document import AppendixCData, DenseEvidenceRow


def _appendix_c_page(c: Canvas, plan: AppendixCRenderPlan) -> None:
    title_y = draw_appendix_title_bar(
        c,
        title=_tr(plan.lang, "REPORT_APPENDIX_C_TITLE"),
        width=PAGE_W - 2 * MARGIN,
        page_top=PAGE_H - MARGIN,
    )
    width = PAGE_W - 2 * MARGIN
    chain_y = _draw_appendix_c_evidence_chain_panel(c, plan=plan, width=width, title_y=title_y)
    measurement_y = _draw_appendix_c_measurement_panel(
        c,
        plan=plan,
        width=width,
        chain_y=chain_y,
    )
    _draw_appendix_c_lower_panels(
        c,
        plan=plan,
        width=width,
        measurement_y=measurement_y,
    )


def _draw_appendix_c_evidence_chain_panel(
    c: Canvas,
    *,
    plan: AppendixCRenderPlan,
    width: float,
    title_y: float,
) -> float:
    appendix = plan.appendix
    chain_h = _evidence_chain_panel_height(appendix)
    chain_y = title_y - chain_h
    chain_region = draw_panel_region(
        c,
        x=MARGIN,
        y=chain_y,
        w=width,
        h=chain_h,
        title=_tr(plan.lang, "REPORT_EVIDENCE_CHAIN_TITLE"),
    )
    chain_top = draw_text_block(
        c,
        region=chain_region,
        y=chain_region.content_top,
        text=appendix.evidence_summary or _tr(plan.lang, "REPORT_EVIDENCE_CHAIN_NOTE"),
        size=FS_SMALL,
        color=SUB_CLR,
        leading=FS_SMALL + 1.0,
        max_lines=3,
        after_gap=1.0 * mm,
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
            human_location(row.dominant_location, lang=plan.lang)
            if row.dominant_location
            else _tr(plan.lang, "UNKNOWN"),
        ]
        if show_ambiguity:
            current.append(row.ambiguity_note or "—")
        chain_rows.append(current)
    if show_ambiguity:
        chain_headers.append(_tr(plan.lang, "REPORT_AMBIGUITY_COLUMN"))
        chain_widths = [0.15, 0.16, 0.13, 0.10, 0.13, 0.11, 0.22]
    _draw_table(
        c,
        x=chain_region.content_x,
        y=chain_top,
        w=chain_region.content_w,
        y_bottom=chain_region.content_bottom,
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
    return chain_y


def _draw_appendix_c_measurement_panel(
    c: Canvas,
    *,
    plan: AppendixCRenderPlan,
    width: float,
    chain_y: float,
) -> float:
    appendix = plan.appendix
    measurement_h = _measurement_panel_height(appendix)
    measurement_y = chain_y - GAP - measurement_h
    measurement_region = draw_panel_region(
        c,
        x=MARGIN,
        y=measurement_y,
        w=width,
        h=measurement_h,
        title=_measurement_panel_title(appendix, lang=plan.lang),
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
    measurement_top = measurement_region.content_top
    if shared_measurement_context:
        measurement_top = draw_text_block(
            c,
            region=measurement_region,
            y=measurement_top,
            text=_tr(
                plan.lang,
                "REPORT_SUPPORTING_MEASUREMENTS_SHARED_CONTEXT",
                source=next(iter(measurement_source_values)),
                signal=next(iter(measurement_signal_values)),
                speed=next(iter(measurement_speed_values)),
                location=human_location(next(iter(measurement_location_values)), lang=plan.lang),
            ),
            size=FS_SMALL,
            color=TEXT_CLR,
            leading=FS_SMALL + 1.0,
            max_lines=1,
            after_gap=0.8 * mm,
        )
    measurement_top = _draw_measurement_panel_guide(
        c,
        plan=plan,
        appendix=appendix,
        y=measurement_top,
        region=measurement_region,
    )
    measurement_headers, measurement_rows, measurement_widths = _measurement_table_content(
        plan,
        appendix=appendix,
        shared_measurement_context=shared_measurement_context,
    )
    _draw_table(
        c,
        x=measurement_region.content_x,
        y=measurement_top,
        w=measurement_region.content_w,
        y_bottom=measurement_region.content_bottom,
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
    return float(measurement_y)


def _draw_appendix_c_lower_panels(
    c: Canvas,
    *,
    plan: AppendixCRenderPlan,
    width: float,
    measurement_y: float,
) -> None:
    appendix = plan.appendix
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
    context_region = draw_panel_region(
        c,
        x=MARGIN,
        y=lower_y,
        w=context_w,
        h=lower_h,
        title=_tr(plan.lang, "REPORT_SUPPORTING_CONTEXT_TITLE"),
    )
    block_y = context_region.content_top
    if appendix.context_summary:
        block_y = draw_text_block(
            c,
            region=context_region,
            y=block_y,
            text=appendix.context_summary,
            size=FS_SMALL,
            color=SUB_CLR,
            leading=FS_SMALL + 1.0,
            max_lines=4,
            after_gap=1.2 * mm,
        )
    for snapshot in appendix.evidence_snapshot_rows[:5]:
        block_y, did_draw = draw_section_block_if_room(
            c,
            region=context_region,
            y=block_y,
            title=snapshot.label,
            body=snapshot.value or _tr(plan.lang, "UNKNOWN"),
            max_lines=3,
        )
        if not did_draw:
            block_y = _draw_context_overflow_note(
                c,
                region=context_region,
                y=block_y,
                lang=plan.lang,
            )
            break
    did_draw = True
    show_speed_phase = bool(appendix.speed_band_summary or appendix.phase_summary) or not bool(
        appendix.observations
    )
    if show_speed_phase:
        block_y, did_draw = draw_section_block_if_room(
            c,
            region=context_region,
            y=block_y,
            title=_tr(plan.lang, "REPORT_SPEED_BAND_SUMMARY_LABEL"),
            body=appendix.speed_band_summary or _tr(plan.lang, "UNKNOWN"),
            max_lines=3,
        )
        if did_draw:
            block_y, did_draw = draw_section_block_if_room(
                c,
                region=context_region,
                y=block_y,
                title=_tr(plan.lang, "REPORT_PHASE_SUMMARY_LABEL"),
                body=appendix.phase_summary or _tr(plan.lang, "UNKNOWN"),
                max_lines=3,
            )
    if not did_draw:
        block_y = _draw_context_overflow_note(
            c,
            region=context_region,
            y=block_y,
            lang=plan.lang,
        )
    if appendix.observations and block_y > lower_y + 8 * mm:
        observations_text = "\n".join(f"- {item}" for item in appendix.observations[:2])
        block_y, did_draw = draw_section_block_if_room(
            c,
            region=context_region,
            y=block_y,
            title=_tr(plan.lang, "ADDITIONAL_OBSERVATIONS"),
            body=observations_text,
            max_lines=4,
        )
        if not did_draw:
            _draw_context_overflow_note(
                c,
                region=context_region,
                y=block_y,
                lang=plan.lang,
            )

    suitability_x = MARGIN + context_w + GAP
    suitability_region = draw_panel_region(
        c,
        x=suitability_x,
        y=lower_y,
        w=suitability_w,
        h=lower_h,
        title=_tr(plan.lang, "REPORT_SUITABILITY_DETAIL_TITLE"),
    )
    trust_y = suitability_region.content_top
    filtered_suitability_items = [
        item for item in appendix.suitability_items if item.detail != plan.action_status_note
    ]
    if appendix.limits_summary:
        trust_y = draw_text_block(
            c,
            region=suitability_region,
            y=trust_y,
            text=appendix.limits_summary,
            size=FS_SMALL,
            color=SUB_CLR,
            leading=FS_SMALL + 1.0,
            max_lines=4,
            after_gap=1.0 * mm,
        )
    for item in filtered_suitability_items[:5]:
        trust_y = (
            _draw_text(
                c,
                suitability_region.content_x,
                trust_y,
                suitability_region.content_w,
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
                    suitability_region.content_x,
                    trust_y,
                    suitability_region.content_w,
                    item.detail,
                    size=FS_SMALL,
                    color=SUB_CLR,
                    leading=FS_SMALL + 1.0,
                    max_lines=2,
                )
                - 0.8 * mm
            )

    trace_x = suitability_x + suitability_w + GAP
    trace_region = draw_panel_region(
        c,
        x=trace_x,
        y=lower_y,
        w=trace_w,
        h=lower_h,
        title=_tr(plan.lang, "REPORT_TRACEABILITY_PANEL_TITLE"),
    )
    trace_y = trace_region.content_top
    for trace_row in plan.trace_rows:
        trace_y = (
            _draw_traceability_row(
                c,
                trace_row,
                x=trace_region.content_x,
                y=trace_y,
                w=trace_region.content_w,
            )
            - 0.4 * mm
        )
        if trace_y < trace_region.content_bottom:
            break


def _draw_context_overflow_note(
    c: Canvas,
    *,
    region: PanelRegion,
    y: float,
    lang: str,
) -> float:
    return draw_overflow_note_if_room(
        c,
        region=region,
        y=y,
        text=_tr(lang, "REPORT_CONTEXT_MORE_NOT_SHOWN"),
    )


def _measurement_panel_title(appendix: AppendixCData, *, lang: str) -> str:
    if appendix.dense_evidence_rows:
        return _tr(lang, "REPORT_DENSE_EVIDENCE_TITLE")
    if appendix.proof_window_rows:
        return _tr(lang, "REPORT_SUPPORTING_WINDOWS_TITLE")
    return _tr(lang, "REPORT_SUPPORTING_MEASUREMENTS_TITLE")


def _draw_measurement_panel_guide(
    c: Canvas,
    *,
    plan: AppendixCRenderPlan,
    appendix: AppendixCData,
    y: float,
    region: PanelRegion,
) -> float:
    if appendix.dense_evidence_rows:
        top = draw_text_block(
            c,
            region=region,
            y=y,
            text=_tr(plan.lang, "REPORT_DENSE_EVIDENCE_GUIDE"),
            size=FS_SMALL,
            color=SUB_CLR,
            leading=FS_SMALL + 1.0,
            max_lines=2,
            after_gap=0.8 * mm,
        )
        return float(
            _draw_dense_evidence_charts(
                c,
                x=region.content_x,
                y=top,
                w=region.content_w,
                rows=appendix.dense_evidence_rows,
                lang=plan.lang,
            )
            - 1.0 * mm
        )
    if appendix.measurement_guide:
        return draw_text_block(
            c,
            region=region,
            y=y,
            text=appendix.measurement_guide,
            size=FS_SMALL,
            color=SUB_CLR,
            leading=FS_SMALL + 1.0,
            max_lines=2,
            after_gap=0.8 * mm,
        )
    return y


def _measurement_table_content(
    plan: AppendixCRenderPlan,
    *,
    appendix: AppendixCData,
    shared_measurement_context: bool,
) -> tuple[list[str], list[list[str]], list[float]]:
    if appendix.dense_evidence_rows:
        return _dense_measurement_table_content(plan, appendix=appendix)
    if appendix.proof_window_rows:
        return _proof_window_table_content(plan, appendix=appendix)
    if shared_measurement_context:
        return _shared_measurement_table_content(plan, appendix=appendix)
    return _measurement_table_with_context_content(plan, appendix=appendix)


def _dense_measurement_table_content(
    plan: AppendixCRenderPlan,
    *,
    appendix: AppendixCData,
) -> tuple[list[str], list[list[str]], list[float]]:
    headers = [
        _tr(plan.lang, "REPORT_SOURCE_COLUMN"),
        _tr(plan.lang, "ORDER_LABEL"),
        _tr(plan.lang, "CONFIDENCE_LABEL"),
        _tr(plan.lang, "REPORT_DENSE_EVIDENCE_SUPPORT_COLUMN"),
        _tr(plan.lang, "FREQUENCY_HZ"),
        _tr(plan.lang, "REPORT_PEAK_DB_COLUMN"),
        _tr(plan.lang, "REPORT_LOCATION_COLUMN"),
        _tr(plan.lang, "REPORT_DENSE_EVIDENCE_CAVEAT_COLUMN"),
    ]
    rows = [
        [
            row.source_name,
            row.order_label,
            row.confidence_label,
            row.support,
            row.frequency_band,
            _fmt_db(row.peak_db),
            human_location(row.strongest_location, lang=plan.lang)
            if row.strongest_location
            else _tr(plan.lang, "UNKNOWN"),
            row.caveat or "—",
        ]
        for row in appendix.dense_evidence_rows
    ]
    return headers, rows, [0.12, 0.13, 0.13, 0.14, 0.13, 0.09, 0.12, 0.14]


def _proof_window_table_content(
    plan: AppendixCRenderPlan,
    *,
    appendix: AppendixCData,
) -> tuple[list[str], list[list[str]], list[float]]:
    speed_unit = "km/u" if plan.lang == "nl" else "km/h"
    headers = [
        _tr(plan.lang, "REPORT_WINDOW_ID_COLUMN"),
        _tr(plan.lang, "REPORT_TIME_COLUMN"),
        _tr(plan.lang, "REPORT_SPEED_COLUMN"),
        _tr(plan.lang, "FREQUENCY_HZ"),
        _tr(plan.lang, "REPORT_LOCATION_COLUMN"),
        _tr(plan.lang, "REPORT_PHASE_COLUMN"),
    ]
    rows = [
        [
            row.window_id,
            f"{row.time_s:.1f} s" if row.time_s is not None else _tr(plan.lang, "UNKNOWN"),
            (
                f"{row.speed_kmh:.0f} {speed_unit}"
                if row.speed_kmh is not None
                else _tr(plan.lang, "UNKNOWN")
            ),
            _fmt_hz(row.matched_hz),
            human_location(row.dominant_location, lang=plan.lang)
            if row.dominant_location
            else _tr(plan.lang, "UNKNOWN"),
            row.phase or _tr(plan.lang, "UNKNOWN"),
        ]
        for row in appendix.proof_window_rows
    ]
    return headers, rows, [0.11, 0.14, 0.16, 0.18, 0.20, 0.21]


def _shared_measurement_table_content(
    plan: AppendixCRenderPlan,
    *,
    appendix: AppendixCData,
) -> tuple[list[str], list[list[str]], list[float]]:
    headers = [
        _tr(plan.lang, "REPORT_MEASUREMENT_ID_COLUMN"),
        _tr(plan.lang, "FREQUENCY_HZ"),
        _tr(plan.lang, "REPORT_PEAK_DB_COLUMN"),
        _tr(plan.lang, "REPORT_STRENGTH_DB_COLUMN"),
    ]
    rows = [
        [
            row.measurement_id,
            _fmt_hz(row.frequency_hz),
            _fmt_db(row.peak_db),
            _fmt_db(row.strength_db),
        ]
        for row in appendix.measurement_rows
    ]
    return headers, rows, [0.18, 0.22, 0.30, 0.30]


def _measurement_table_with_context_content(
    plan: AppendixCRenderPlan,
    *,
    appendix: AppendixCData,
) -> tuple[list[str], list[list[str]], list[float]]:
    headers = [
        _tr(plan.lang, "REPORT_MEASUREMENT_ID_COLUMN"),
        _tr(plan.lang, "REPORT_SOURCE_COLUMN"),
        _tr(plan.lang, "REPORT_SIGNAL_COLUMN"),
        _tr(plan.lang, "REPORT_PEAK_DB_COLUMN"),
        _tr(plan.lang, "REPORT_STRENGTH_DB_COLUMN"),
        _tr(plan.lang, "REPORT_SPEED_WINDOW_COLUMN"),
        _tr(plan.lang, "REPORT_LOCATION_COLUMN"),
    ]
    rows = [
        [
            row.measurement_id,
            row.source_name,
            row.signal_label,
            _fmt_db(row.peak_db),
            _fmt_db(row.strength_db),
            row.speed_window or _tr(plan.lang, "UNKNOWN"),
            human_location(row.dominant_location, lang=plan.lang)
            if row.dominant_location
            else _tr(plan.lang, "UNKNOWN"),
        ]
        for row in appendix.measurement_rows
    ]
    return headers, rows, [0.10, 0.16, 0.18, 0.10, 0.10, 0.17, 0.19]


def _evidence_chain_panel_height(appendix: AppendixCData) -> float:
    row_count = len(appendix.evidence_chain_rows)
    extra_rows = max(0, row_count - 3)
    return float(min(76 * mm, 58 * mm + (extra_rows * 12 * mm)))


def _draw_dense_evidence_charts(
    c: Canvas,
    *,
    x: float,
    y: float,
    w: float,
    rows: list[DenseEvidenceRow],
    lang: str,
) -> float:
    chart_rows = rows[:3]
    if not chart_rows:
        return y
    c.setFont(FONT_B, FS_SMALL)
    c.setFillColor(SUB_CLR)
    c.drawString(x, y, _tr(lang, "REPORT_DENSE_EVIDENCE_CHART_LABEL"))
    cursor = float(y - 3.5 * mm)
    label_w = float(w * 0.26)
    bar_x = float(x + label_w + 2 * mm)
    bar_w = float(w * 0.48)
    value_x = float(bar_x + bar_w + 3 * mm)
    bar_h = float(2.2 * mm)
    for row in chart_rows:
        support_ratio = max(0.0, min(1.0, row.support_ratio))
        reference_ratio = row.reference_coverage_ratio
        if reference_ratio is None:
            reference_ratio = 1.0
        reference_ratio = max(0.0, min(1.0, reference_ratio))
        label = f"{row.source_name} {row.order_label}".strip()
        c.setFont(FONT, FS_SMALL)
        c.setFillColor(TEXT_CLR)
        c.drawString(x, cursor + 0.1 * mm, label[:30])
        c.setFillColor(REPORT_COLORS["surface_alt"])
        c.rect(bar_x, cursor, bar_w, bar_h, fill=1, stroke=0)
        c.setFillColor(REPORT_COLORS["brand_surface"])
        c.rect(bar_x, cursor, bar_w * reference_ratio, bar_h, fill=1, stroke=0)
        c.setFillColor(REPORT_COLORS["brand"])
        c.rect(bar_x, cursor, bar_w * support_ratio, bar_h, fill=1, stroke=0)
        c.setFillColor(SUB_CLR)
        c.drawString(
            value_x,
            cursor + 0.1 * mm,
            _tr(
                lang,
                "REPORT_DENSE_EVIDENCE_CHART_VALUE",
                support=f"{support_ratio * 100:.0f}%",
                reference=f"{reference_ratio * 100:.0f}%",
            ),
        )
        cursor = float(cursor - 4.4 * mm)
    return cursor


def _measurement_panel_height(appendix: AppendixCData) -> float:
    dense_row_count = len(appendix.dense_evidence_rows)
    if dense_row_count:
        extra_rows = max(0, dense_row_count - 3)
        return float(min(104 * mm, 88 * mm + (extra_rows * 12 * mm)))
    proof_window_count = len(appendix.proof_window_rows)
    if proof_window_count:
        extra_rows = max(0, proof_window_count - 4)
        return float(min(98 * mm, 72 * mm + (extra_rows * 12 * mm)))
    measurement_count = len(appendix.measurement_rows)
    extra_rows = max(0, measurement_count - 4)
    return float(min(92 * mm, 72 * mm + (extra_rows * 10 * mm)))
