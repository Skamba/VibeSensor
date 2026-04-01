"""Appendix page composition for the redesigned diagnostic report PDF."""

from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.panels._panel_title_bar import _draw_title_bar
from vibesensor.adapters.pdf.pdf_diagram_render import car_location_diagram
from vibesensor.adapters.pdf.pdf_drawing import _draw_panel, _hex
from vibesensor.adapters.pdf.pdf_style import (
    FONT,
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
    _measure_section_block_height,
    _measure_text_height,
    _wrap_lines,
)
from vibesensor.adapters.pdf.report_data import (
    AppendixAData,
    NextStep,
    ReportLabelValueRow,
    ReportTemplateData,
)
from vibesensor.report_i18n import tr as _tr


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


def _estimate_appendix_c_context_panel_height(
    appendix: ReportTemplateData, *, width: float
) -> float:
    appendix_c = appendix.appendix_c
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
    total += _measure_section_block_height(
        appendix_c.speed_band_summary or _tr(appendix.lang, "UNKNOWN"),
        w=content_w,
        max_lines=3,
    )
    total += _measure_section_block_height(
        appendix_c.phase_summary or _tr(appendix.lang, "UNKNOWN"),
        w=content_w,
        max_lines=3,
    )
    if appendix_c.observations:
        observations_text = "\n".join(f"- {item}" for item in appendix_c.observations[:2])
        total += _measure_section_block_height(observations_text, w=content_w, max_lines=6)
    return float(max(34 * mm, total + 3 * mm))


def _estimate_appendix_c_suitability_panel_height(
    appendix: ReportTemplateData, *, width: float
) -> float:
    appendix_c = appendix.appendix_c
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
        item
        for item in appendix_c.suitability_items
        if item.detail != appendix.verdict_page.action_status_note
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


def _estimate_appendix_c_trace_panel_height(
    appendix_d: ReportTemplateData, *, width: float
) -> float:
    content_w = width - 8 * mm
    total = PANEL_HEADER_H + 2 * mm
    for row in appendix_d.appendix_d.rows:
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
    return float(min(48 * mm, max(34 * mm, table_height + 17 * mm)))


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


def _worksheet_first_actions_panel_height(appendix: AppendixAData, *, lang: str) -> float:
    title_y = PAGE_H - MARGIN - (12 * mm) - GAP
    top_h = _estimate_worksheet_top_panel_height(appendix, lang=lang)
    top_y = title_y - top_h
    stack_h = _estimate_worksheet_ranked_stack_height(appendix, lang=lang)
    if stack_h > 0.0:
        stack_y = top_y - GAP - stack_h
        return float(stack_y - (MARGIN + 8 * mm))
    return float(top_y - GAP - (MARGIN + 8 * mm))


def _worksheet_continuation_panel_height() -> float:
    title_y = PAGE_H - MARGIN - (12 * mm) - GAP
    return float(title_y - (MARGIN + 8 * mm))


def _estimate_action_steps_panel_height(steps: list[NextStep], *, width: float) -> float:
    inner_w = width - 8 * mm
    gaps_h = max(len(steps) - 1, 0) * 2.5 * mm
    cards_h = sum(_estimate_action_step_card_height(step, width=inner_w) for step in steps)
    return float(max(PANEL_HEADER_H + 12 * mm, PANEL_HEADER_H + 7 * mm + cards_h + gaps_h))


def _fit_action_steps(steps: list[NextStep], *, panel_w: float, panel_h: float) -> int:
    inner_w = panel_w - 8 * mm
    row_y = panel_h - PANEL_HEADER_H - 2 * mm
    count = 0
    for step in steps:
        estimated_h = _estimate_action_step_card_height(step, width=inner_w)
        if row_y - estimated_h < 4 * mm:
            break
        row_y = row_y - estimated_h - 2.5 * mm
        count += 1
    return count


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


def _estimate_action_step_card_height(step: NextStep, *, width: float) -> float:
    title_lines = _wrap_lines(step.action, width - 18 * mm, FS_BODY)[:2]
    why_lines = _wrap_lines(step.why or "", width - 12 * mm, FS_SMALL)[:3] if step.why else []
    detail_w = (width - 18 * mm) / 2
    confirm_lines = _wrap_lines(step.confirm or "", detail_w, FS_SMALL)[:3] if step.confirm else []
    clean_lines = _wrap_lines(step.falsify or "", detail_w, FS_SMALL)[:3] if step.falsify else []
    bottom_lines = max(len(confirm_lines), len(clean_lines), 1)
    return float(
        max(
            28 * mm,
            10 * mm
            + (len(title_lines) * (FS_BODY + 1.2))
            + (len(why_lines) * (FS_SMALL + 1.0))
            + 8 * mm
            + (bottom_lines * (FS_SMALL + 1.0)),
        )
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


def _draw_traceability_row(
    c: Canvas, row: ReportLabelValueRow, *, x: float, y: float, w: float
) -> float:
    c.setFillColor(_hex(SUB_CLR))
    c.setFont(FONT, FS_SMALL)
    c.drawString(x, y, row.label)
    return _draw_text(
        c,
        x,
        y - 3.4 * mm,
        w,
        row.value,
        font=FONT_B,
        size=FS_BODY,
        color=TEXT_CLR,
        leading=FS_BODY + 1.2,
        max_lines=3,
    )


def _fmt_db(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.1f} dB"


def _fmt_hz(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.1f} Hz"


def _draw_table(
    c: Canvas,
    *,
    x: float,
    y: float,
    w: float,
    y_bottom: float,
    headers: list[str],
    rows: list[list[str]],
    col_widths: list[float],
    max_body_lines: int = 2,
) -> None:
    total_ratio = sum(col_widths)
    widths = [w * (ratio / total_ratio) for ratio in col_widths]
    header_lines = [
        _wrap_lines(header, width_part - 3 * mm, FS_SMALL)
        for width_part, header in zip(widths, headers, strict=False)
    ]
    header_line_count = max((len(lines) for lines in header_lines), default=1)
    header_leading = FS_SMALL + 1.0
    header_h = max(8 * mm, (header_line_count * header_leading) + 3.5 * mm)
    c.setFillColor(_hex(REPORT_COLORS["surface_alt"]))
    c.setStrokeColor(_hex(REPORT_COLORS["border"]))
    c.rect(x, y - header_h, w, header_h, stroke=1, fill=1)
    cursor_x = x
    for width_part, lines in zip(widths, header_lines, strict=False):
        c.setFillColor(_hex(TEXT_CLR))
        c.setFont(FONT_B, FS_SMALL)
        line_y = y - 3.2 * mm
        for line in lines[:2]:
            c.drawString(cursor_x + 1.5 * mm, line_y, line)
            line_y -= header_leading
        cursor_x += width_part
    current_y = y - header_h
    for row_index, row in enumerate(rows):
        line_counts = []
        for cell, width_part in zip(row, widths, strict=False):
            line_counts.append(max(1, len(_wrap_lines(str(cell), width_part - 3 * mm, FS_SMALL))))
        row_h = max(9 * mm, min(max_body_lines, max(line_counts)) * (FS_SMALL + 1.2) + 3.5 * mm)
        if current_y - row_h < y_bottom:
            break
        fill = "#ffffff" if row_index % 2 == 0 else REPORT_COLORS["surface"]
        c.setFillColor(_hex(fill))
        c.setStrokeColor(_hex(REPORT_COLORS["table_row_border"]))
        c.rect(x, current_y - row_h, w, row_h, stroke=1, fill=1)
        cursor_x = x
        for cell, width_part in zip(row, widths, strict=False):
            _draw_text(
                c,
                cursor_x + 1.5 * mm,
                current_y - 3.0 * mm,
                width_part - 3 * mm,
                str(cell),
                size=FS_SMALL,
                color=TEXT_CLR,
                leading=FS_SMALL + 1.0,
                max_lines=max_body_lines,
            )
            cursor_x += width_part
        current_y -= row_h
