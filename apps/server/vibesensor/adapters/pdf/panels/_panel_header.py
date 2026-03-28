"""Header and observed-signature panels for PDF page 1."""

from __future__ import annotations

from collections.abc import Callable

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.pdf_drawing import (
    _cert_display,
    _draw_panel,
    _hex,
    _safe,
    _strength_with_peak,
)
from vibesensor.adapters.pdf.pdf_style import (
    DISCLAIMER_Y_OFFSET,
    FONT,
    FONT_B,
    FS_BODY,
    FS_H2,
    FS_SMALL,
    FS_TITLE,
    GAP,
    MARGIN,
    MUTED_CLR,
    OBSERVED_LABEL_W,
    PAGE_H,
    PANEL_HEADER_H,
    REPORT_COLORS,
    HeaderColumnsLayout,
    build_page1_layout,
    observed_signature_row_count,
    show_observed_signature_location,
)
from vibesensor.adapters.pdf.pdf_text import (
    _draw_kv,
    _draw_kv_column,
    _draw_text,
    _kv_consumed_height,
)
from vibesensor.adapters.pdf.report_data import ReportTemplateData


def _first_check_target(data: ReportTemplateData, *, fallback: str) -> str:
    if data.system_cards and data.system_cards[0].parts:
        return _safe(data.system_cards[0].parts[0].name, fallback)
    return _safe(data.observed.strongest_location, fallback)


def _label_width(c: Canvas, label: str, *, default_w: float, col_w: float) -> float:
    measured = c.stringWidth(f"{label}:", FONT, FS_BODY) + 1.2 * mm
    max_allowed = max(default_w, col_w - 20 * mm)
    return float(min(max(default_w, measured), max_allowed))


def _column_height(
    rows: list[tuple[str, str, float]],
    *,
    available_w: float,
    row_gap: float,
) -> float:
    if not rows:
        return 0.0
    total = 0.0
    for idx, (_label, value, label_w) in enumerate(rows):
        value_w = max(20 * mm, available_w - label_w)
        total += _kv_consumed_height(value, fs=FS_BODY, value_w=value_w)
        if idx < len(rows) - 1:
            total += row_gap
    return total


def _build_header_rows(
    c: Canvas,
    data: ReportTemplateData,
    *,
    tr: Callable[[str], str],
    columns: HeaderColumnsLayout,
    na: str,
) -> tuple[list[tuple[str, str, float]], list[tuple[str, str, float]], float, float, float]:
    meta_right = columns.meta_right
    left_col_w = columns.left_col_w
    right_lbl_default = 27 * mm
    right_col_w = columns.right_col_w
    left_lbl_default = 22 * mm

    car_parts = [p for p in (_safe(data.car_name, ""), _safe(data.car_type, "")) if p]
    car_text = " — ".join(car_parts) if car_parts else na

    left_rows: list[tuple[str, str, float]] = [
        (
            tr("RUN_DATE"),
            _safe(data.run_datetime),
            _label_width(c, tr("RUN_DATE"), default_w=left_lbl_default, col_w=left_col_w),
        ),
        (
            tr("CAR_LABEL"),
            car_text,
            _label_width(c, tr("CAR_LABEL"), default_w=12 * mm, col_w=left_col_w),
        ),
    ]
    if data.start_time_utc:
        left_rows.append(
            (
                tr("START_TIME_UTC"),
                data.start_time_utc,
                _label_width(
                    c,
                    tr("START_TIME_UTC"),
                    default_w=left_lbl_default,
                    col_w=left_col_w,
                ),
            ),
        )
    if data.end_time_utc:
        left_rows.append(
            (
                tr("END_TIME_UTC"),
                data.end_time_utc,
                _label_width(c, tr("END_TIME_UTC"), default_w=left_lbl_default, col_w=left_col_w),
            ),
        )

    right_pairs: list[tuple[str, str]] = []
    if data.run_id:
        right_pairs.append((tr("RUN_ID"), data.run_id))
    if data.duration_text:
        right_pairs.append((tr("DURATION"), data.duration_text))
    if data.sensor_count:
        sensor_info = str(data.sensor_count)
        if data.sensor_locations:
            sensor_info += f" ({', '.join(data.sensor_locations[:4])})"
        right_pairs.append((tr("SENSORS_LABEL"), sensor_info))
    if data.sensor_model:
        right_pairs.append((tr("SENSOR_MODEL"), data.sensor_model))
    if data.firmware_version:
        right_pairs.append((tr("FIRMWARE_VERSION"), data.firmware_version))
    if data.sample_count:
        right_pairs.append((tr("SAMPLE_COUNT_LABEL"), str(data.sample_count)))
    if data.sample_rate_hz:
        right_pairs.append((tr("RAW_SAMPLE_RATE_HZ_LABEL"), data.sample_rate_hz))
    if data.tire_spec_text:
        right_pairs.append((tr("TIRE_SIZE"), data.tire_spec_text))

    right_rows = [
        (
            label,
            value,
            _label_width(c, label, default_w=right_lbl_default, col_w=right_col_w),
        )
        for label, value in right_pairs
    ]
    return left_rows, right_rows, left_col_w, right_col_w, meta_right


def _draw_header_panel(
    c: Canvas,
    data: ReportTemplateData,
    *,
    tr: Callable[[str], str],
    width: float,
    page_top: float,
    na: str,
) -> float:
    obs_rows = observed_signature_row_count(
        certainty_tier_key=data.certainty_tier_key,
        system_card_count=len(data.system_cards),
        has_certainty_reason=bool(data.observed.certainty_reason),
    )
    header_columns = build_page1_layout(
        width=width,
        page_top=page_top,
        header_content_height=0.0,
        observed_rows=obs_rows,
    ).header_columns
    left_rows, right_rows, left_col_w, right_col_w, meta_right = _build_header_rows(
        c,
        data,
        tr=tr,
        columns=header_columns,
        na=na,
    )
    left_h = _column_height(left_rows, available_w=left_col_w, row_gap=header_columns.meta_row_gap)
    right_h = _column_height(
        right_rows,
        available_w=right_col_w,
        row_gap=header_columns.meta_row_gap,
    )
    layout = build_page1_layout(
        width=width,
        page_top=page_top,
        header_content_height=max(left_h, right_h),
        observed_rows=obs_rows,
    )
    _draw_panel(
        c,
        layout.header.x,
        layout.header.y,
        layout.header.w,
        layout.header.h,
        fill=REPORT_COLORS["brand_surface"],
    )

    c.setFillColor(_hex(REPORT_COLORS["brand"]))
    c.setFont(FONT_B, FS_TITLE)
    c.drawString(
        MARGIN + 4 * mm,
        layout.header.y + layout.header.h - 6 * mm,
        data.title or tr("REPORT_FOOTER_TITLE"),
    )

    meta_y0 = layout.header.y + layout.header.h - header_columns.meta_top_pad
    _draw_kv_column(
        c,
        header_columns.meta_x,
        meta_y0,
        left_rows,
        left_col_w,
        header_columns.meta_row_gap,
    )
    _draw_kv_column(c, meta_right, meta_y0, right_rows, right_col_w, header_columns.meta_row_gap)
    return float(layout.header.y - GAP)


def _draw_observed_signature_panel(
    c: Canvas,
    data: ReportTemplateData,
    *,
    tr: Callable[[str], str],
    width: float,
    y_cursor: float,
    na: str,
) -> float:
    show_strongest_sensor = show_observed_signature_location(
        certainty_tier_key=data.certainty_tier_key,
        system_card_count=len(data.system_cards),
    )
    obs_rows = observed_signature_row_count(
        certainty_tier_key=data.certainty_tier_key,
        system_card_count=len(data.system_cards),
        has_certainty_reason=bool(data.observed.certainty_reason),
    )
    layout = build_page1_layout(
        width=width,
        page_top=PAGE_H - MARGIN,
        header_content_height=0.0,
        observed_rows=obs_rows,
    )
    obs_step = 4.2 * mm
    observed_panel = layout.observed
    obs_y = y_cursor - observed_panel.h
    ox = MARGIN + 4 * mm
    oy = obs_y + observed_panel.h - PANEL_HEADER_H
    inspect_target = _first_check_target(data, fallback=na)
    cert_val = _cert_display(data.observed.certainty_label, data.observed.certainty_pct, na)

    _draw_panel(c, MARGIN, obs_y, width, observed_panel.h, tr("OBSERVED_SIGNATURE"))
    oy = _draw_text(
        c,
        ox,
        oy,
        width - 8 * mm,
        _safe(data.observed.primary_system, na),
        font=FONT_B,
        size=FS_TITLE,
    )
    oy = _draw_kv(
        c,
        ox,
        oy,
        tr("WHAT_TO_CHECK_FIRST"),
        inspect_target,
        label_w=OBSERVED_LABEL_W,
        fs=FS_H2,
        value_w=width - 8 * mm - OBSERVED_LABEL_W,
    )
    oy -= 1.0 * mm
    if show_strongest_sensor:
        _draw_kv(
            c,
            ox,
            oy,
            tr("STRONGEST_SENSOR"),
            _safe(data.observed.strongest_location, na),
            label_w=OBSERVED_LABEL_W,
        )
        oy -= obs_step
    _draw_kv(c, ox, oy, tr("CERTAINTY_LABEL_FULL"), cert_val, label_w=OBSERVED_LABEL_W)
    oy -= obs_step
    _draw_kv(
        c,
        ox,
        oy,
        tr("SPEED_BAND"),
        _safe(data.observed.speed_band, na),
        label_w=OBSERVED_LABEL_W,
    )
    oy -= obs_step
    _draw_kv(
        c,
        ox,
        oy,
        tr("STRENGTH"),
        _strength_with_peak(
            data.observed.strength_label,
            data.observed.strength_peak_db,
            fallback=na,
            peak_suffix=tr("STRENGTH_PEAK_SUFFIX"),
        ),
        label_w=OBSERVED_LABEL_W,
    )
    oy -= obs_step
    if data.observed.certainty_reason:
        _draw_kv(
            c,
            ox,
            oy,
            tr("CERTAINTY_REASON"),
            data.observed.certainty_reason,
            label_w=OBSERVED_LABEL_W,
            value_w=width - 8 * mm - OBSERVED_LABEL_W,
        )
    if data.certainty_tier_key == "A":
        oy -= obs_step
        _draw_text(
            c,
            ox,
            oy,
            width - 8 * mm,
            tr("INSUFFICIENT_CONFIDENCE_TITLE"),
            size=FS_BODY,
            color="#c0392b",
        )
    _draw_text(
        c,
        ox,
        obs_y + DISCLAIMER_Y_OFFSET,
        width - 8 * mm,
        tr("PATTERN_SUGGESTION_DISCLAIMER"),
        size=FS_SMALL,
        color=MUTED_CLR,
    )
    return float(obs_y - GAP)
