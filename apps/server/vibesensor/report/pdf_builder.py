"""PDF report builder – Canvas-based 2-page diagnostic worksheet layout.

Page 1: Diagnostic worksheet (header, observed signature, systems with
         findings, next steps, data trust).
Page 2: Evidence & diagnostics (car visual, pattern evidence panel,
         diagnostic peaks table).

Based on the report_template_v2 layout specification.  Uses the low-level
ReportLab Canvas API for pixel-precise positioning.
"""

from __future__ import annotations

import logging
import textwrap
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from ..report_i18n import tr as _tr
from ..report_theme import REPORT_COLORS
from .pdf_diagram import car_location_diagram
from .pdf_helpers import location_hotspots
from .report_data import (
    NextStep,
    PatternEvidence,
    ReportTemplateData,
    SystemFindingCard,
    map_summary,
)

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Style tokens (aligned with report_theme and template specification)
# ---------------------------------------------------------------------------

PAGE_SIZE = A4
PAGE_W, PAGE_H = PAGE_SIZE
MARGIN = 11 * mm

TEXT_CLR = REPORT_COLORS["text_primary"]
SUB_CLR = REPORT_COLORS["text_secondary"]
MUTED_CLR = REPORT_COLORS["text_muted"]
LINE_CLR = REPORT_COLORS["border"]
PANEL_BG = "#ffffff"
SOFT_BG = REPORT_COLORS["surface"]
WARN_CLR = REPORT_COLORS["warning"]

FONT = "Helvetica"
FONT_B = "Helvetica-Bold"
FS_TITLE = 12
FS_H2 = 9
FS_BODY = 7
FS_SMALL = 6

R_CARD = 6
GAP = 4 * mm
OBSERVED_LABEL_W = 28 * mm
DATA_TRUST_WIDTH_RATIO = 0.32
DATA_TRUST_LABEL_W = 27 * mm
EVIDENCE_CAR_PANEL_WIDTH_RATIO = 0.50
DISCLAIMER_Y_OFFSET = 5.5 * mm
DATA_TRUST_LINE_STEP = 3.9 * mm
CAR_PANEL_TITLE_RESERVE = 18 * mm


# ---------------------------------------------------------------------------
# Low-level drawing helpers
# ---------------------------------------------------------------------------


def _hex(c: str) -> colors.Color:
    return colors.HexColor(c)


def _safe(v: str | None, fallback: str = "—") -> str:
    return str(v).strip() if v and str(v).strip() else fallback


def _strength_with_peak(
    strength_label: str | None,
    peak_amp_g: float | None,
    *,
    fallback: str,
) -> str:
    base = _safe(strength_label, fallback)
    if peak_amp_g is None:
        return base
    if "g peak" in base.lower():
        return base
    return f"{base} · {peak_amp_g:.3f} g peak"


def _draw_panel(
    c: Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    title: str | None = None,
    fill: str = PANEL_BG,
    border: str = LINE_CLR,
) -> None:
    c.setFillColor(_hex(fill))
    c.setStrokeColor(_hex(border))
    c.roundRect(x, y, w, h, R_CARD, stroke=1, fill=1)
    if title:
        c.setFillColor(_hex(TEXT_CLR))
        c.setFont(FONT_B, FS_H2)
        c.drawString(x + 4 * mm, y + h - 5.5 * mm, title)


def _wrap_lines(text: str, width_pt: float, font_size: int) -> list[str]:
    avg_char_w = font_size * 0.48
    max_chars = max(10, int(width_pt / avg_char_w))
    lines: list[str] = []
    for paragraph in text.split("\n"):
        lines.extend(textwrap.wrap(paragraph, width=max_chars) or [""])
    return lines


def _measure_text_height(
    text: str,
    width_pt: float,
    font_size: int,
    leading: float | None = None,
) -> float:
    """Return the total height consumed by wrapped text."""
    if leading is None:
        leading = font_size + 2
    lines = _wrap_lines(text, width_pt, font_size)
    return max(len(lines), 1) * leading


def _draw_text(
    c: Canvas,
    x: float,
    y_top: float,
    w: float,
    text: str,
    *,
    font: str = FONT,
    size: int = FS_BODY,
    color: str = TEXT_CLR,
    leading: float | None = None,
    max_lines: int | None = None,
) -> float:
    """Draw wrapped text top-down.  Returns the y after the last line."""
    if leading is None:
        leading = size + 2
    lines = _wrap_lines(text, w, size)
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        if lines:
            last = lines[-1]
            lines[-1] = (last[: len(last) - 3] + "\u2026") if len(last) > 3 else "\u2026"
    c.setFillColor(_hex(color))
    c.setFont(font, size)
    y = y_top
    for line in lines:
        c.drawString(x, y, line)
        y -= leading
    return y


def _draw_kv(
    c: Canvas,
    x: float,
    y: float,
    label: str,
    value: str,
    *,
    label_w: float = 30 * mm,
    fs: int = FS_BODY,
    value_w: float | None = None,
) -> float:
    """Draw a label: value pair.  Returns the y after the last line."""
    c.setFillColor(_hex(SUB_CLR))
    c.setFont(FONT, fs)
    c.drawString(x, y, f"{label}:")
    c.setFillColor(_hex(TEXT_CLR))
    val_font = FONT_B if fs >= 8 else FONT
    c.setFont(val_font, fs)
    if value_w is not None:
        lines = _wrap_lines(value, value_w, fs)
        leading = fs + 2
        vy = y
        for line in lines:
            c.drawString(x + label_w, vy, line)
            vy -= leading
        return vy
    c.drawString(x + label_w, y, value)
    return y - (fs + 2)


def _draw_footer(c: Canvas, page_num: int, total: int, version: str) -> None:
    y = MARGIN - 4 * mm
    c.setFont(FONT, 6)
    c.setFillColor(_hex(MUTED_CLR))
    c.drawString(MARGIN, y, version)
    c.drawRightString(PAGE_W - MARGIN, y, f"{page_num} / {total}")


# ---------------------------------------------------------------------------
# Aspect-ratio protection (template specification)
# ---------------------------------------------------------------------------


def fit_rect_preserve_aspect(
    src_w: float,
    src_h: float,
    box_x: float,
    box_y: float,
    box_w: float,
    box_h: float,
) -> tuple[float, float, float, float]:
    """Return (x, y, w, h) fitted inside box while preserving src aspect."""
    if src_w <= 0 or src_h <= 0:
        return box_x, box_y, box_w, box_h
    src_ratio = src_w / src_h
    box_ratio = box_w / box_h if box_h else src_ratio
    if box_ratio > src_ratio:
        h = box_h
        w = h * src_ratio
        x = box_x + (box_w - w) / 2
        y = box_y
    else:
        w = box_w
        h = w / src_ratio
        x = box_x
        y = box_y + (box_h - h) / 2
    return x, y, w, h


def assert_aspect_preserved(
    src_w: float,
    src_h: float,
    drawn_w: float,
    drawn_h: float,
    tolerance: float = 0.03,
) -> None:
    """Raise if aspect ratio deviates more than *tolerance* (3 %)."""
    if src_w <= 0 or src_h <= 0 or drawn_w <= 0 or drawn_h <= 0:
        raise AssertionError("Invalid dimensions for aspect ratio check")
    src_ratio = src_w / src_h
    drawn_ratio = drawn_w / drawn_h
    delta = abs(drawn_ratio - src_ratio) / src_ratio
    if delta > tolerance:
        raise AssertionError(
            f"Car visual aspect ratio distorted. src={src_ratio:.4f}, "
            f"drawn={drawn_ratio:.4f}, delta={delta:.2%}"
        )


# ---------------------------------------------------------------------------
# Page 1 — Diagnostic Worksheet
# ---------------------------------------------------------------------------


def _page1(c: Canvas, data: ReportTemplateData) -> None:  # noqa: C901
    """Render the full page-1 worksheet layout."""
    m = MARGIN
    W = PAGE_W - 2 * m

    def tr(key: str) -> str:
        return _tr(data.lang, key)

    page_top = PAGE_H - m
    na = tr("UNKNOWN")

    # -- Header panel (title + date + car) --
    hdr_h = 32 * mm
    hdr_y = page_top - hdr_h
    _draw_panel(c, m, hdr_y, W, hdr_h, fill=SOFT_BG)

    c.setFillColor(_hex(TEXT_CLR))
    c.setFont(FONT_B, FS_TITLE)
    c.drawString(m + 4 * mm, hdr_y + hdr_h - 6 * mm, data.title or tr("DIAGNOSTIC_WORKSHEET"))

    meta_x = m + 4 * mm
    meta_step = 3.8 * mm
    y_meta = hdr_y + hdr_h - 12 * mm
    meta_lbl_w = 22 * mm

    # Left column metadata
    _draw_kv(
        c, meta_x, y_meta, tr("RUN_DATE"), _safe(data.run_datetime), label_w=meta_lbl_w, fs=FS_BODY
    )
    y_meta -= meta_step
    car_parts = [p for p in (_safe(data.car.name, ""), _safe(data.car.car_type, "")) if p]
    car_text = " \u2014 ".join(car_parts) if car_parts else na
    _draw_kv(c, meta_x, y_meta, tr("CAR_LABEL"), car_text, label_w=12 * mm, fs=FS_BODY)
    y_meta -= meta_step
    if data.start_time_utc:
        _draw_kv(
            c,
            meta_x,
            y_meta,
            tr("START_TIME_UTC"),
            data.start_time_utc,
            label_w=meta_lbl_w,
            fs=FS_BODY,
        )
        y_meta -= meta_step
    if data.end_time_utc:
        _draw_kv(
            c, meta_x, y_meta, tr("END_TIME_UTC"), data.end_time_utc, label_w=meta_lbl_w, fs=FS_BODY
        )

    # Right column metadata — stacked vertically, never on one cramped line
    meta_right = meta_x + 95 * mm
    right_lbl_w = 27 * mm
    y_right = hdr_y + hdr_h - 12 * mm
    if data.run_id:
        _draw_kv(c, meta_right, y_right, tr("RUN_ID"), data.run_id, label_w=16 * mm, fs=FS_BODY)
        y_right -= meta_step
    if data.duration_text:
        _draw_kv(
            c,
            meta_right,
            y_right,
            tr("DURATION"),
            data.duration_text,
            label_w=right_lbl_w,
            fs=FS_BODY,
        )
        y_right -= meta_step
    if data.sensor_count:
        sensor_info = str(data.sensor_count)
        if data.sensor_locations:
            sensor_info += f" ({', '.join(data.sensor_locations[:4])})"
        _draw_kv(
            c,
            meta_right,
            y_right,
            tr("SENSORS_LABEL"),
            sensor_info,
            label_w=right_lbl_w,
            fs=FS_BODY,
        )
        y_right -= meta_step
    if data.sensor_model:
        _draw_kv(
            c,
            meta_right,
            y_right,
            tr("SENSOR_MODEL"),
            data.sensor_model,
            label_w=right_lbl_w,
            fs=FS_BODY,
        )
        y_right -= meta_step
    if data.firmware_version:
        firmware_label = "Firmwareversie" if data.lang == "nl" else "Firmware Version"
        _draw_kv(
            c,
            meta_right,
            y_right,
            firmware_label,
            data.firmware_version,
            label_w=right_lbl_w,
            fs=FS_BODY,
        )
        y_right -= meta_step
    if data.sample_count:
        _draw_kv(
            c,
            meta_right,
            y_right,
            tr("SAMPLE_COUNT_LABEL"),
            str(data.sample_count),
            label_w=right_lbl_w,
            fs=FS_BODY,
        )
        y_right -= meta_step
    if data.sample_rate_hz:
        _draw_kv(
            c,
            meta_right,
            y_right,
            tr("RAW_SAMPLE_RATE_HZ_LABEL"),
            data.sample_rate_hz,
            label_w=right_lbl_w,
            fs=FS_BODY,
        )
        y_right -= meta_step
    if data.tire_spec_text:
        _draw_kv(
            c,
            meta_right,
            y_right,
            tr("TIRE_SIZE"),
            data.tire_spec_text,
            label_w=right_lbl_w,
            fs=FS_BODY,
        )

    y_cursor = hdr_y - GAP

    # -- Observed signature (full-width, dynamic height) --
    # Pre-measure content to determine panel height
    obs_rows = 5  # primary, sensor, speed, strength, certainty
    if data.observed.certainty_reason:
        obs_rows += 1
    obs_step = 4.2 * mm
    obs_content_h = obs_rows * obs_step + 6 * mm  # content + disclaimer reserve
    obs_h = max(32 * mm, 10.5 * mm + obs_content_h + 4 * mm)
    obs_y = y_cursor - obs_h
    lw = OBSERVED_LABEL_W

    _draw_panel(c, m, obs_y, W, obs_h, tr("OBSERVED_SIGNATURE"))
    ox = m + 4 * mm
    oy = obs_y + obs_h - 10.5 * mm

    _draw_kv(c, ox, oy, tr("PRIMARY_SYSTEM"), _safe(data.observed.primary_system, na), label_w=lw)
    oy -= obs_step
    _draw_kv(
        c,
        ox,
        oy,
        tr("STRONGEST_SENSOR"),
        _safe(data.observed.strongest_sensor_location, na),
        label_w=lw,
    )
    oy -= obs_step
    _draw_kv(c, ox, oy, tr("SPEED_BAND"), _safe(data.observed.speed_band, na), label_w=lw)
    oy -= obs_step
    _draw_kv(
        c,
        ox,
        oy,
        tr("STRENGTH"),
        _strength_with_peak(
            data.observed.strength_label, data.observed.strength_peak_amp_g, fallback=na
        ),
        label_w=lw,
    )
    oy -= obs_step

    cert_val = _safe(data.observed.certainty_label, na)
    if data.observed.certainty_pct:
        cert_val = f"{cert_val} ({data.observed.certainty_pct})"
    _draw_kv(c, ox, oy, tr("CERTAINTY_LABEL_FULL"), cert_val, label_w=lw)
    oy -= obs_step
    if data.observed.certainty_reason:
        _draw_kv(
            c,
            ox,
            oy,
            tr("CERTAINTY_REASON"),
            data.observed.certainty_reason,
            label_w=lw,
            value_w=W - 8 * mm - lw,
        )

    # Disclaimer at bottom of observed panel
    disc_text = tr("PATTERN_SUGGESTION_DISCLAIMER")
    _draw_text(
        c, ox, obs_y + DISCLAIMER_Y_OFFSET, W - 8 * mm, disc_text, size=FS_SMALL, color=MUTED_CLR
    )

    y_cursor = obs_y - GAP

    # -- Systems with findings panel --
    cards = data.system_cards[:2]
    n_cards = len(cards) if cards else 0
    cards_h = 58 * mm
    cards_y = y_cursor - cards_h
    _draw_panel(c, m, cards_y, W, cards_h, tr("SYSTEMS_WITH_FINDINGS"))

    inner_x = m + 4 * mm
    inner_w = W - 8 * mm
    inner_top = cards_y + cards_h - 10.5 * mm

    if not cards:
        c.setFillColor(_hex(SUB_CLR))
        c.setFont(FONT, FS_BODY)
        c.drawString(inner_x, inner_top, tr("NO_SYSTEMS_WITH_FINDINGS"))
    else:
        card_gap = 3 * mm
        card_w = (inner_w - card_gap * max(n_cards - 1, 1)) / max(n_cards, 1)
        card_h = cards_h - 14 * mm
        for idx, card in enumerate(cards):
            cx = inner_x + idx * (card_w + card_gap)
            cy = cards_y + 3 * mm
            _draw_system_card(c, cx, cy, card_w, card_h, card, tr=tr)

    y_cursor = cards_y - GAP

    # -- Bottom row: next steps + data trust --
    # Use remaining vertical space for next_steps and data_trust
    footer_reserve = 8 * mm
    available_h = y_cursor - m - footer_reserve
    next_h = max(44 * mm, min(available_h, 52 * mm))
    next_y = y_cursor - next_h
    trust_w = W * DATA_TRUST_WIDTH_RATIO
    next_w = W - trust_w - GAP
    _draw_panel(c, m, next_y, next_w, next_h, tr("NEXT_STEPS"))

    nx = m + 4 * mm
    ny = next_y + next_h - 11 * mm

    if not data.next_steps:
        c.setFillColor(_hex(SUB_CLR))
        c.setFont(FONT, FS_BODY)
        c.drawString(nx, ny, tr("NO_NEXT_STEPS"))
    else:
        _draw_next_steps_table(c, nx, ny, next_w - 8 * mm, next_y + 3 * mm, data.next_steps)

    # Data Trust (right-bottom)
    trust_x = m + next_w + GAP
    _draw_panel(c, trust_x, next_y, trust_w, next_h, tr("DATA_TRUST"))
    tx = trust_x + 4 * mm
    ty = next_y + next_h - 10.5 * mm
    trust_val_w = trust_w - 8 * mm - DATA_TRUST_LABEL_W
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


def _draw_system_card(
    c: Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    card: SystemFindingCard,
    *,
    tr,
) -> None:
    """Render a single system-finding card."""
    na = tr("NOT_AVAILABLE")

    c.setFillColor(_hex(SOFT_BG))
    c.setStrokeColor(_hex(LINE_CLR))
    c.roundRect(x, y, w, h, 4, stroke=1, fill=1)

    cx = x + 3 * mm
    cy = y + h - 4 * mm

    c.setFillColor(_hex(TEXT_CLR))
    c.setFont(FONT_B, 8)
    c.drawString(cx, cy, card.system_name)

    c.setFillColor(_hex(SUB_CLR))
    c.setFont(FONT, 7)
    c.drawString(
        cx,
        cy - 4 * mm,
        f"{tr('STRONGEST_SENSOR')}: {_safe(card.strongest_location, na)}",
    )

    _draw_text(
        c,
        cx,
        cy - 8 * mm,
        w - 6 * mm,
        _safe(card.pattern_summary, na),
        size=7,
        color=SUB_CLR,
        max_lines=1,
    )

    # Parts list
    parts_y = y + h - 21 * mm
    c.setFillColor(_hex(TEXT_CLR))
    c.setFont(FONT_B, 7)
    c.drawString(cx, parts_y, tr("COMMON_PARTS"))

    py = parts_y - 3.6 * mm
    c.setFont(FONT, 6.7)
    for p in card.parts[:3]:
        if py <= y + 3 * mm:
            break
        c.setFillColor(_hex(TEXT_CLR))
        c.drawString(cx, py, f"\u2022 {p.name}")
        py -= 3.2 * mm


def _draw_next_steps_table(
    c: Canvas,
    x: float,
    y_top: float,
    w: float,
    y_bottom: float,
    steps: list[NextStep],
) -> None:
    """Draw ordered next-steps rows with multi-line wrapping."""
    col1_w = 12 * mm
    text_w = w - col1_w - 4
    min_row_h = 6.6 * mm
    fs = 7
    leading = fs + 2

    y = y_top
    for idx, step in enumerate(steps[:5], start=1):
        action_text = step.action
        if step.why:
            action_text += f" \u2014 {step.why}"

        # Measure how many lines this step needs
        lines = _wrap_lines(action_text, text_w, fs)
        n_lines = max(len(lines), 1)
        row_h = max(min_row_h, n_lines * leading + 2 * mm)

        if y - row_h < y_bottom:
            break

        bg = SOFT_BG if idx % 2 == 0 else PANEL_BG
        c.setFillColor(_hex(bg))
        c.setStrokeColor(_hex(LINE_CLR))
        c.rect(x, y - row_h, w, row_h, stroke=1, fill=1)

        c.setFillColor(_hex(TEXT_CLR))
        c.setFont(FONT_B, fs)
        c.drawString(x + 2, y - 4.4 * mm, f"{idx}.")

        _draw_text(
            c,
            x + col1_w,
            y - 2 * mm,
            text_w,
            action_text,
            font=FONT,
            size=fs,
            color=TEXT_CLR,
            max_lines=3,
        )
        y -= row_h


# ---------------------------------------------------------------------------
# Page 2 — Evidence & Diagnostics
# ---------------------------------------------------------------------------

# BMW body proportions for aspect-ratio protection.
_BMW_LENGTH_MM = 5007.0
_BMW_WIDTH_MM = 1894.0


def _page2(  # noqa: C901
    c: Canvas,
    data: ReportTemplateData,
    *,
    summary: dict,
    location_rows: list,
    top_causes: list,
    tr_fn,
    text_fn,
) -> None:
    """Render page-2: car visual + pattern evidence + peaks table."""
    m = MARGIN
    W = PAGE_W - 2 * m
    page_top = PAGE_H - m

    def tr(key: str) -> str:
        return _tr(data.lang, key)

    # -- Title bar --
    title_h = 12 * mm
    title_y = page_top - title_h
    _draw_panel(c, m, title_y, W, title_h, fill=SOFT_BG)
    c.setFillColor(_hex(TEXT_CLR))
    c.setFont(FONT_B, 11)
    c.drawString(m + 4 * mm, title_y + 3.5 * mm, tr("EVIDENCE_DIAGNOSTICS"))

    y_cursor = title_y - GAP

    # -- Two-column: left = car visual, right = pattern evidence --
    left_w = W * EVIDENCE_CAR_PANEL_WIDTH_RATIO
    right_w = W - left_w - GAP
    main_h = 118 * mm

    left_y = y_cursor - main_h

    # Car visual panel
    _draw_panel(c, m, left_y, left_w, main_h, tr("EVIDENCE_AND_HOTSPOTS"))

    # Compute aspect-preserving box for the car diagram
    inner_pad = 5 * mm
    box_x = m + inner_pad
    box_y = left_y + inner_pad
    box_w = left_w - 2 * inner_pad
    box_h = main_h - CAR_PANEL_TITLE_RESERVE  # leave room for panel title and whitespace

    # The car is taller than wide (top-down view, length > width)
    src_w = _BMW_WIDTH_MM
    src_h = _BMW_LENGTH_MM
    dx, dy, dw, dh = fit_rect_preserve_aspect(src_w, src_h, box_x, box_y, box_w, box_h)

    # Assert aspect ratio is preserved
    assert_aspect_preserved(src_w, src_h, dw, dh, tolerance=0.03)

    # Render the real car diagram as a ReportLab Drawing
    findings = summary.get("findings", [])
    diagram = car_location_diagram(
        top_causes or (findings if isinstance(findings, list) else []),
        summary,
        location_rows,
        content_width=W,
        tr=tr_fn,
        text_fn=text_fn,
        diagram_width=dw,
        diagram_height=dh,
    )
    diagram.drawOn(c, dx, dy)

    # Pattern evidence panel (right)
    _draw_pattern_evidence(c, m + left_w + GAP, left_y, right_w, main_h, data.pattern_evidence, tr)

    y_cursor = left_y - GAP

    # -- Peaks table --
    table_h = 53 * mm
    table_y = y_cursor - table_h
    _draw_panel(c, m, table_y, W, table_h, tr("DIAGNOSTIC_PEAKS"))
    _draw_peaks_table(
        c, m + 4 * mm, table_y + table_h - 10 * mm, W - 8 * mm, table_y + 3 * mm, data, tr
    )

    transient_findings = [
        finding
        for finding in findings
        if isinstance(finding, dict)
        and str(finding.get("severity") or "").strip().lower() == "info"
        and (
            str(finding.get("suspected_source") or "").strip().lower() == "transient_impact"
            or str(finding.get("peak_classification") or "").strip().lower() == "transient"
        )
    ]
    if transient_findings:
        obs_h = 24 * mm
        obs_y = table_y - GAP - obs_h
        _draw_additional_observations(c, m, obs_y, W, obs_h, transient_findings, tr)


def _draw_pattern_evidence(
    c: Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    ev: PatternEvidence,
    tr,
) -> None:
    na = tr("NOT_AVAILABLE")

    _draw_panel(c, x, y, w, h, tr("PATTERN_EVIDENCE"))

    rx = x + 4 * mm
    ry = y + h - 10.5 * mm
    lw = 28 * mm
    val_w = w - 8 * mm - lw

    systems_text = ", ".join(ev.matched_systems) if ev.matched_systems else na
    ry = _draw_kv(c, rx, ry, tr("MATCHED_SYSTEMS"), systems_text, label_w=lw, fs=7, value_w=val_w)
    ry -= 1.0 * mm
    ry = _draw_kv(
        c, rx, ry, tr("STRONGEST_SENSOR"), _safe(ev.strongest_location, na), label_w=lw, fs=7
    )
    ry -= 1.0 * mm
    ry = _draw_kv(c, rx, ry, tr("SPEED_BAND"), _safe(ev.speed_band, na), label_w=lw, fs=7)
    ry -= 1.0 * mm
    ry = _draw_kv(
        c,
        rx,
        ry,
        tr("STRENGTH"),
        _strength_with_peak(ev.strength_label, ev.strength_peak_amp_g, fallback=na),
        label_w=lw,
        fs=7,
        value_w=val_w,
    )
    ry -= 1.0 * mm

    # Certainty — split label/pct and reason to avoid overflow
    cert_val = _safe(ev.certainty_label, na)
    if ev.certainty_pct:
        cert_val = f"{cert_val} ({ev.certainty_pct})"
    ry = _draw_kv(c, rx, ry, tr("CERTAINTY_LABEL_FULL"), cert_val, label_w=lw, fs=7)
    ry -= 0.5 * mm
    if ev.certainty_reason:
        ry = _draw_text(
            c,
            rx + 2 * mm,
            ry,
            val_w + lw - 2 * mm,
            ev.certainty_reason,
            size=6,
            color=SUB_CLR,
            max_lines=2,
        )
    ry -= 2.0 * mm

    # Warning
    if ev.warning:
        c.setFillColor(_hex(WARN_CLR))
        c.setFont(FONT_B, FS_SMALL)
        c.drawString(rx, ry, f"\u26a0 {tr('WARNING_LABEL')}")
        ry -= 3.0 * mm
        ry = _draw_text(c, rx, ry, w - 8 * mm, ev.warning, size=6, color=WARN_CLR, max_lines=3)
        ry -= 1.5 * mm

    # Interpretation
    c.setFillColor(_hex(TEXT_CLR))
    c.setFont(FONT_B, FS_SMALL)
    c.drawString(rx, ry, tr("INTERPRETATION"))
    ry -= 3.2 * mm
    ry = _draw_text(
        c, rx, ry, w - 8 * mm, _safe(ev.interpretation, na), size=6, color=SUB_CLR, max_lines=4
    )
    ry -= 1.5 * mm

    # Why parts listed
    c.setFillColor(_hex(TEXT_CLR))
    c.setFont(FONT_B, FS_SMALL)
    c.drawString(rx, ry, tr("WHY_PARTS_LISTED"))
    ry -= 3.0 * mm
    _draw_text(
        c, rx, ry, w - 8 * mm, _safe(ev.why_parts_text, na), size=6, color=SUB_CLR, max_lines=4
    )


def _draw_peaks_table(
    c: Canvas,
    x: float,
    y_top: float,
    w: float,
    y_bottom: float,
    data: ReportTemplateData,
    tr,
) -> None:
    """Diagnostic-first peaks table."""
    col_defs = [
        (tr("RANK"), 12 * mm),
        (tr("SYSTEM"), 24 * mm),
        (tr("FREQUENCY_HZ"), 18 * mm),
        (tr("ORDER_LABEL"), 24 * mm),
        (tr("PEAK_AMP_G"), 18 * mm),
        (tr("STRENGTH_DB"), 16 * mm),
        (tr("SPEED_BAND"), 22 * mm),
    ]
    used = sum(cw for _, cw in col_defs)
    notes_w = max(20 * mm, w - used)
    col_defs.append((tr("RELEVANCE"), notes_w))

    row_h = 6.2 * mm
    y = y_top

    # Header row
    c.setFillColor(_hex(SOFT_BG))
    c.setStrokeColor(_hex(LINE_CLR))
    c.rect(x, y - row_h + 1, w, row_h, stroke=1, fill=1)
    c.setFillColor(_hex(SUB_CLR))
    c.setFont(FONT_B, 6.5)
    cx_off = x + 1.5
    for label, cw in col_defs:
        c.drawString(cx_off, y - 4.2 * mm, label)
        cx_off += cw

    # Data rows
    c.setFont(FONT, 6.5)
    rows = data.peak_rows[:6]
    if not rows:
        y -= row_h
        c.setFillColor(_hex(PANEL_BG))
        c.rect(x, y - row_h + 1, w, row_h, stroke=1, fill=1)
        c.setFillColor(_hex(MUTED_CLR))
        c.drawString(x + 2, y - 4.2 * mm, "\u2014")
        return

    for idx, row in enumerate(rows, start=1):
        y -= row_h
        if y - row_h < y_bottom:
            break
        bg = SOFT_BG if idx % 2 == 0 else PANEL_BG
        c.setFillColor(_hex(bg))
        c.rect(x, y - row_h + 1, w, row_h, stroke=1, fill=1)
        c.setFillColor(_hex(TEXT_CLR))
        cx_off = x + 1.5
        vals = [
            row.rank,
            row.system,
            row.freq_hz,
            row.order,
            row.amp_g,
            row.strength_db,
            row.speed_band,
            row.relevance,
        ]
        for val, (_, cw) in zip(vals, col_defs, strict=True):
            c.drawString(cx_off, y - 4.2 * mm, val)
            cx_off += cw


def _draw_additional_observations(
    c: Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    transient_findings: list[dict[str, object]],
    tr,
) -> None:
    _draw_panel(c, x, y, w, h, tr("ADDITIONAL_OBSERVATIONS"), fill=SOFT_BG)
    c.setFillColor(_hex(MUTED_CLR))
    c.setFont(FONT, 6.5)

    y_cursor = y + h - 10 * mm
    for finding in transient_findings[:3]:
        order_label = str(finding.get("frequency_hz_or_order") or "").strip()
        if not order_label:
            order_label = tr("SOURCE_TRANSIENT_IMPACT")
        confidence = float(finding.get("confidence_0_to_1") or 0.0)
        line = f"• {order_label} ({confidence * 100.0:.0f}%)"
        c.drawString(x + 4 * mm, y_cursor, line)
        y_cursor -= 3.5 * mm


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_report_pdf(summary: dict[str, object]) -> bytes:
    """Build a 2-page diagnostic-worksheet PDF from a run summary dict."""
    try:
        return _build_canvas_pdf(summary)
    except Exception as exc:
        LOGGER.error("PDF generation failed.", exc_info=True)
        raise RuntimeError("PDF generation failed") from exc


def _build_canvas_pdf(summary: dict) -> bytes:
    data = map_summary(summary)
    lang = data.lang

    def tr_fn(key: str, **kw: object) -> str:
        return _tr(lang, key, **kw)

    def text_fn(en: str, nl: str) -> str:
        return nl if lang == "nl" else en

    # Compute location hotspot rows for the car diagram
    findings = summary.get("findings", [])
    actionable_findings = [
        f
        for f in findings
        if isinstance(f, dict)
        and not str(f.get("finding_id") or "").strip().upper().startswith("REF_")
    ]
    location_rows, _, _, _ = location_hotspots(
        summary.get("samples", []),
        findings,
        tr=tr_fn,
        text_fn=text_fn,
    )
    top_causes_all = [c for c in summary.get("top_causes", []) if isinstance(c, dict)]
    top_causes_non_ref = [
        c
        for c in top_causes_all
        if not str(c.get("finding_id") or "").strip().upper().startswith("REF_")
    ]
    top_causes_actionable = [
        c
        for c in top_causes_non_ref
        if str(c.get("source") or c.get("suspected_source") or "").strip().lower()
        not in {"unknown_resonance", "unknown"}
        or str(c.get("strongest_location") or "").strip().lower()
        not in {"", "unknown", "not available", "n/a"}
    ]
    top_causes = (
        top_causes_actionable or actionable_findings or top_causes_non_ref or top_causes_all
    )

    buf = BytesIO()
    c = Canvas(buf, pagesize=PAGE_SIZE, pageCompression=0)

    # Page 1
    _page1(c, data)
    _draw_footer(c, 1, 2, data.version_marker)
    c.showPage()

    # Page 2
    _page2(
        c,
        data,
        summary=summary,
        location_rows=location_rows,
        top_causes=top_causes,
        tr_fn=tr_fn,
        text_fn=text_fn,
    )
    _draw_footer(c, 2, 2, data.version_marker)
    c.showPage()

    c.save()
    return buf.getvalue()
