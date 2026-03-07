"""Section renderers used by the page-1 worksheet composition."""

from __future__ import annotations

from collections.abc import Callable

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from .pdf_drawing import _cert_display, _draw_panel, _hex, _safe, _strength_with_peak
from .pdf_page_layouts import HeaderColumnsLayout, build_page1_layout
from .pdf_style import (
    DATA_TRUST_LABEL_W,
    DISCLAIMER_Y_OFFSET,
    FONT,
    FONT_B,
    FS_BODY,
    FS_SMALL,
    FS_TITLE,
    GAP,
    MARGIN,
    MUTED_CLR,
    OBSERVED_LABEL_W,
    PAGE_H,
    PANEL_HEADER_H,
    SOFT_BG,
    SUB_CLR,
    TEXT_CLR,
)
from .pdf_text import _draw_kv, _draw_kv_column, _draw_text, _kv_consumed_height
from .report_data import NextStep, ReportTemplateData


def label_width(c: Canvas, label: str, *, default_w: float, col_w: float) -> float:
    measured = c.stringWidth(f"{label}:", FONT, FS_BODY) + 1.2 * mm
    max_allowed = max(default_w, col_w - 20 * mm)
    return min(max(default_w, measured), max_allowed)


def column_height(
    rows: list[tuple[str, str, float]], *, available_w: float, row_gap: float
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


def build_header_rows(
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

    car_parts = [p for p in (_safe(data.car.name, ""), _safe(data.car.car_type, "")) if p]
    car_text = " \u2014 ".join(car_parts) if car_parts else na

    left_rows: list[tuple[str, str, float]] = [
        (
            tr("RUN_DATE"),
            _safe(data.run_datetime),
            label_width(c, tr("RUN_DATE"), default_w=left_lbl_default, col_w=left_col_w),
        ),
        (
            tr("CAR_LABEL"),
            car_text,
            label_width(c, tr("CAR_LABEL"), default_w=12 * mm, col_w=left_col_w),
        ),
    ]
    if data.start_time_utc:
        left_rows.append(
            (
                tr("START_TIME_UTC"),
                data.start_time_utc,
                label_width(
                    c,
                    tr("START_TIME_UTC"),
                    default_w=left_lbl_default,
                    col_w=left_col_w,
                ),
            )
        )
    if data.end_time_utc:
        left_rows.append(
            (
                tr("END_TIME_UTC"),
                data.end_time_utc,
                label_width(c, tr("END_TIME_UTC"), default_w=left_lbl_default, col_w=left_col_w),
            )
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
            label_width(c, label, default_w=right_lbl_default, col_w=right_col_w),
        )
        for label, value in right_pairs
    ]
    return left_rows, right_rows, left_col_w, right_col_w, meta_right


def render_header_panel(
    c: Canvas,
    data: ReportTemplateData,
    *,
    tr: Callable[[str], str],
    width: float,
    page_top: float,
    na: str,
) -> float:
    header_columns = build_page1_layout(
        width=width,
        page_top=page_top,
        header_content_height=0.0,
        observed_rows=5,
    ).header_columns
    left_rows, right_rows, left_col_w, right_col_w, meta_right = build_header_rows(
        c,
        data,
        tr=tr,
        columns=header_columns,
        na=na,
    )
    left_h = column_height(left_rows, available_w=left_col_w, row_gap=header_columns.meta_row_gap)
    right_h = column_height(
        right_rows,
        available_w=right_col_w,
        row_gap=header_columns.meta_row_gap,
    )
    layout = build_page1_layout(
        width=width,
        page_top=page_top,
        header_content_height=max(left_h, right_h),
        observed_rows=5 + (1 if data.observed.certainty_reason else 0),
    )
    _draw_panel(c, layout.header.x, layout.header.y, layout.header.w, layout.header.h, fill=SOFT_BG)

    c.setFillColor(_hex(TEXT_CLR))
    c.setFont(FONT_B, FS_TITLE)
    c.drawString(
        MARGIN + 4 * mm,
        layout.header.y + layout.header.h - 6 * mm,
        data.title or tr("DIAGNOSTIC_WORKSHEET"),
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
    return layout.header.y - GAP


def render_observed_signature_panel(
    c: Canvas,
    data: ReportTemplateData,
    *,
    tr: Callable[[str], str],
    width: float,
    y_cursor: float,
    na: str,
) -> float:
    obs_rows = 5 + (1 if data.observed.certainty_reason else 0)
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

    _draw_panel(c, MARGIN, obs_y, width, observed_panel.h, tr("OBSERVED_SIGNATURE"))
    _draw_kv(
        c,
        ox,
        oy,
        tr("PRIMARY_SYSTEM"),
        _safe(data.observed.primary_system, na),
        label_w=OBSERVED_LABEL_W,
    )
    oy -= obs_step
    _draw_kv(
        c,
        ox,
        oy,
        tr("STRONGEST_SENSOR"),
        _safe(data.observed.strongest_sensor_location, na),
        label_w=OBSERVED_LABEL_W,
    )
    oy -= obs_step
    _draw_kv(
        c, ox, oy, tr("SPEED_BAND"), _safe(data.observed.speed_band, na), label_w=OBSERVED_LABEL_W
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
    cert_val = _cert_display(data.observed.certainty_label, data.observed.certainty_pct, na)
    _draw_kv(c, ox, oy, tr("CERTAINTY_LABEL_FULL"), cert_val, label_w=OBSERVED_LABEL_W)
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
    return obs_y - GAP


def render_systems_panel(
    c: Canvas,
    data: ReportTemplateData,
    *,
    tr: Callable[[str], str],
    width: float,
    y_cursor: float,
    draw_system_card: Callable[..., None],
) -> float:
    cards = data.system_cards[:2]
    n_cards = len(cards) if cards else 0
    layout = build_page1_layout(
        width=width,
        page_top=PAGE_H - MARGIN,
        header_content_height=0.0,
        observed_rows=5 + (1 if data.observed.certainty_reason else 0),
    )
    cards_h = layout.systems.h
    cards_y = y_cursor - cards_h
    _draw_panel(c, MARGIN, cards_y, width, cards_h, tr("SYSTEMS_WITH_FINDINGS"))

    inner_x = MARGIN + 4 * mm
    inner_w = width - 8 * mm
    inner_top = cards_y + cards_h - PANEL_HEADER_H
    if data.certainty_tier_key == "A" or not cards:
        msg = (
            tr("TIER_A_NO_SYSTEMS")
            if data.certainty_tier_key == "A"
            else tr("NO_SYSTEMS_WITH_FINDINGS")
        )
        _draw_text(c, inner_x, inner_top, inner_w, msg, size=FS_BODY, color=SUB_CLR)
    else:
        card_gap = 3 * mm
        card_w = (inner_w - card_gap * max(n_cards - 1, 1)) / max(n_cards, 1)
        card_h = cards_h - 14 * mm
        for idx, card in enumerate(cards):
            cx = inner_x + idx * (card_w + card_gap)
            cy = cards_y + 3 * mm
            draw_system_card(c, cx, cy, card_w, card_h, card, tr=tr)
    return cards_y - GAP


def render_data_trust_panel(
    c: Canvas,
    data: ReportTemplateData,
    *,
    tr: Callable[[str], str],
    x: float,
    y: float,
    w: float,
    h: float,
    na: str,
) -> None:
    _draw_panel(c, x, y, w, h, tr("DATA_TRUST"))
    tx = x + 4 * mm
    ty = y + h - PANEL_HEADER_H
    trust_val_w = w - 8 * mm - DATA_TRUST_LABEL_W
    if data.data_trust:
        for item in data.data_trust[:6]:
            icon = "\u2713" if item.state == "pass" else "\u26a0"
            state_lbl = tr("PASS") if item.state == "pass" else tr("WARN_SHORT")
            value = f"{icon} {state_lbl}"
            if item.state != "pass" and item.detail:
                value = f"{icon} {item.detail}"
            new_ty = _draw_kv(
                c,
                tx,
                ty,
                item.check,
                value,
                label_w=DATA_TRUST_LABEL_W,
                fs=FS_SMALL,
                value_w=trust_val_w,
            )
            ty = new_ty - 1.0 * mm
    else:
        c.setFillColor(_hex(SUB_CLR))
        c.setFont(FONT, FS_SMALL)
        c.drawString(tx, ty, na)


def render_bottom_row_panels(
    c: Canvas,
    data: ReportTemplateData,
    *,
    tr: Callable[[str], str],
    width: float,
    y_cursor: float,
    na: str,
    draw_next_steps_table: Callable[..., int],
) -> list[NextStep]:
    layout = build_page1_layout(
        width=width,
        page_top=PAGE_H - MARGIN,
        header_content_height=0.0,
        observed_rows=5 + (1 if data.observed.certainty_reason else 0),
        y_after_systems_source=y_cursor,
    )
    next_panel = layout.bottom.next_steps
    trust_panel = layout.bottom.data_trust

    _draw_panel(c, next_panel.x, next_panel.y, next_panel.w, next_panel.h, tr("NEXT_STEPS"))
    nx = next_panel.x + 4 * mm
    ny = next_panel.y + next_panel.h - 11 * mm
    if not data.next_steps:
        c.setFillColor(_hex(SUB_CLR))
        c.setFont(FONT, FS_BODY)
        c.drawString(nx, ny, tr("NO_NEXT_STEPS"))
        remaining_next_steps: list[NextStep] = []
    else:
        drawn_steps = draw_next_steps_table(
            c,
            nx,
            ny,
            next_panel.w - 8 * mm,
            next_panel.y + 3 * mm,
            data.next_steps,
        )
        remaining_next_steps = data.next_steps[drawn_steps:]

    render_data_trust_panel(
        c,
        data,
        tr=tr,
        x=trust_panel.x,
        y=trust_panel.y,
        w=trust_panel.w,
        h=trust_panel.h,
        na=na,
    )
    return remaining_next_steps
