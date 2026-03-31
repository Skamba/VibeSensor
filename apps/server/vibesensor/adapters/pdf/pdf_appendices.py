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
from vibesensor.adapters.pdf.pdf_text import _draw_section_block, _draw_text, _wrap_lines
from vibesensor.adapters.pdf.report_data import (
    AppendixAData,
    ReportLabelValueRow,
    ReportTemplateData,
)
from vibesensor.report_i18n import tr as _tr


def _appendix_a_page(c: Canvas, data: ReportTemplateData) -> None:
    title_y = _draw_title_bar(
        c,
        title=_tr(data.lang, "REPORT_APPENDIX_A_TITLE"),
        width=PAGE_W - 2 * MARGIN,
        page_top=PAGE_H - MARGIN,
    )
    if data.appendix_a.mode == "recapture":
        _draw_capture_guidance_page(c, data, title_y)
    else:
        _draw_worksheet_page(c, data.appendix_a, data, data.lang, title_y)


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

    chain_h = 50 * mm
    chain_y = title_y - chain_h
    _draw_panel(c, MARGIN, chain_y, width, chain_h, _tr(data.lang, "REPORT_EVIDENCE_CHAIN_TITLE"))
    show_ambiguity = any(bool(row.ambiguity_note) for row in appendix.evidence_chain_rows)
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
            ", ".join(row.measurement_refs) or "—",
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
        y=chain_y + chain_h - 13 * mm,
        w=width - 8 * mm,
        y_bottom=chain_y + 4 * mm,
        headers=chain_headers,
        rows=chain_rows,
        col_widths=chain_widths,
        max_body_lines=3 if show_ambiguity else 2,
    )

    measurement_h = 62 * mm
    measurement_y = chain_y - GAP - measurement_h
    _draw_panel(
        c,
        MARGIN,
        measurement_y,
        width,
        measurement_h,
        _tr(data.lang, "REPORT_SUPPORTING_MEASUREMENTS_TITLE"),
    )
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
    _draw_table(
        c,
        x=MARGIN + 4 * mm,
        y=measurement_y + measurement_h - 13 * mm,
        w=width - 8 * mm,
        y_bottom=measurement_y + 4 * mm,
        headers=[
            _tr(data.lang, "REPORT_MEASUREMENT_ID_COLUMN"),
            _tr(data.lang, "REPORT_SOURCE_COLUMN"),
            _tr(data.lang, "REPORT_SIGNAL_COLUMN"),
            _tr(data.lang, "REPORT_PEAK_DB_COLUMN"),
            _tr(data.lang, "REPORT_STRENGTH_DB_COLUMN"),
            _tr(data.lang, "REPORT_SPEED_WINDOW_COLUMN"),
            _tr(data.lang, "REPORT_LOCATION_COLUMN"),
        ],
        rows=measurement_rows,
        col_widths=[0.10, 0.16, 0.18, 0.10, 0.10, 0.17, 0.19],
        max_body_lines=2,
    )

    lower_h = measurement_y - (MARGIN + 8 * mm)
    lower_y = MARGIN + 8 * mm
    context_w = width * 0.27
    suitability_w = width * 0.40
    trace_w = width - context_w - suitability_w - (2 * GAP)
    _draw_panel(
        c, MARGIN, lower_y, context_w, lower_h, _tr(data.lang, "REPORT_SUPPORTING_CONTEXT_TITLE")
    )
    block_x = MARGIN + 4 * mm
    block_y = lower_y + lower_h - PANEL_HEADER_H - 2 * mm
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
    for item in appendix.suitability_items[:6]:
        text = item.check if not item.detail else f"{item.check}: {item.detail}"
        trust_y = (
            _draw_text(
                c,
                trust_x,
                trust_y,
                suitability_w - 8 * mm,
                text,
                size=FS_SMALL,
                color=TEXT_CLR if item.state == "pass" else SUB_CLR,
                leading=FS_SMALL + 1.1,
                max_lines=3,
            )
            - 0.8 * mm
        )

    trace_x = suitability_x + suitability_w + GAP
    _draw_panel(
        c, trace_x, lower_y, trace_w, lower_h, _tr(data.lang, "REPORT_TRACEABILITY_PANEL_TITLE")
    )
    trace_y = lower_y + lower_h - PANEL_HEADER_H - 2 * mm
    trace_y = (
        _draw_text(
            c,
            trace_x + 4 * mm,
            trace_y,
            trace_w - 8 * mm,
            _tr(data.lang, "REPORT_APPENDIX_D_TITLE"),
            font=FONT_B,
            size=FS_SMALL,
            color=TEXT_CLR,
            leading=FS_SMALL + 1.0,
            max_lines=2,
        )
        - 1.0 * mm
    )
    for trace_row in appendix_d.rows:
        trace_y = (
            _draw_traceability_row(
                c,
                trace_row,
                x=trace_x + 4 * mm,
                y=trace_y,
                w=trace_w - 8 * mm,
            )
            - 0.8 * mm
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
    c: Canvas, appendix: AppendixAData, data: ReportTemplateData, lang: str, title_y: float
) -> None:
    width = PAGE_W - 2 * MARGIN
    top_h = 43 * mm
    top_y = title_y - top_h
    _draw_panel(c, MARGIN, top_y, width, top_h, _tr(lang, "REPORT_PRIMARY_VS_ALTERNATIVE_TITLE"))
    block_x = MARGIN + 4 * mm
    block_y = top_y + top_h - PANEL_HEADER_H - 2 * mm
    block_y = _draw_section_block(
        c,
        block_x,
        block_y,
        width - 8 * mm,
        _tr(lang, "REPORT_PRIMARY_SOURCE_LABEL"),
        appendix.primary_source or _tr(lang, "UNKNOWN"),
        max_lines=2,
    )
    if appendix.alternative_source:
        block_y = _draw_section_block(
            c,
            block_x,
            block_y,
            width - 8 * mm,
            _tr(lang, "REPORT_ALTERNATIVE_SOURCE_LABEL"),
            appendix.alternative_source,
            max_lines=2,
        )
    if appendix.why_primary_first:
        block_y = _draw_section_block(
            c,
            block_x,
            block_y,
            width - 8 * mm,
            _tr(lang, "REPORT_WHY_PRIMARY_FIRST_LABEL"),
            appendix.why_primary_first,
            max_lines=3,
        )
    if appendix.next_if_clean:
        _draw_section_block(
            c,
            block_x,
            block_y,
            width - 8 * mm,
            _tr(lang, "REPORT_IF_PRIMARY_CLEAN_LABEL"),
            appendix.next_if_clean,
            max_lines=3,
        )

    stack_h = 48 * mm
    stack_y = top_y - GAP - stack_h
    _draw_panel(c, MARGIN, stack_y, width, stack_h, _tr(lang, "REPORT_RANKED_SOURCE_STACK_TITLE"))
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

    matrix_h = stack_y - (MARGIN + 8 * mm)
    matrix_y = MARGIN + 8 * mm
    _draw_panel(c, MARGIN, matrix_y, width, matrix_h, _tr(lang, "REPORT_ACTION_MATRIX_TITLE"))
    action_rows = [
        [step.action, step.why or "", step.confirm or "", step.falsify or ""]
        for step in data.next_steps
    ]
    _draw_table(
        c,
        x=MARGIN + 4 * mm,
        y=matrix_y + matrix_h - 13 * mm,
        w=width - 8 * mm,
        y_bottom=matrix_y + 4 * mm,
        headers=[
            _tr(lang, "REPORT_ACTION_COLUMN"),
            _tr(lang, "WHY"),
            _tr(lang, "CONFIRM"),
            _tr(lang, "REPORT_FALSIFY_COLUMN"),
        ],
        rows=action_rows,
        col_widths=[0.25, 0.25, 0.25, 0.25],
        max_body_lines=3,
    )


def _draw_traceability_row(
    c: Canvas, row: ReportLabelValueRow, *, x: float, y: float, w: float
) -> float:
    c.setFillColor(_hex(SUB_CLR))
    c.setFont(FONT, FS_SMALL)
    c.drawString(x, y, row.label)
    return _draw_text(
        c,
        x,
        y - 4.2 * mm,
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
    for row in rows:
        line_counts = []
        for cell, width_part in zip(row, widths, strict=False):
            line_counts.append(max(1, len(_wrap_lines(str(cell), width_part - 3 * mm, FS_SMALL))))
        row_h = max(9 * mm, min(max_body_lines, max(line_counts)) * (FS_SMALL + 1.2) + 3.5 * mm)
        if current_y - row_h < y_bottom:
            break
        c.setFillColor(_hex("#ffffff"))
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
