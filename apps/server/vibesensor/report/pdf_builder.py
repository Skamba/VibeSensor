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
DATA_TRUST_LABEL_W = 22 * mm
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
            lines[-1] = (lines[-1][:-3] + "...") if len(lines[-1]) > 3 else "..."
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
) -> None:
    c.setFillColor(_hex(SUB_CLR))
    c.setFont(FONT, fs)
    c.drawString(x, y, f"{label}:")
    c.setFillColor(_hex(TEXT_CLR))
    c.setFont(FONT_B if fs >= 8 else FONT, fs)
    c.drawString(x + label_w, y, value)


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
    hdr_h = 30 * mm
    hdr_y = page_top - hdr_h
    _draw_panel(c, m, hdr_y, W, hdr_h, fill=SOFT_BG)

    c.setFillColor(_hex(TEXT_CLR))
    c.setFont(FONT_B, FS_TITLE)
    c.drawString(m + 4 * mm, hdr_y + hdr_h - 6 * mm, data.title or tr("DIAGNOSTIC_WORKSHEET"))

    meta_x = m + 4 * mm
    y1 = hdr_y + hdr_h - 12 * mm
    y2 = y1 - 4.5 * mm
    y3 = y2 - 4.5 * mm
    y4 = y3 - 4.5 * mm
    y5 = y4 - 4.5 * mm

    _draw_kv(c, meta_x, y1, tr("RUN_DATE"), _safe(data.run_datetime), label_w=22 * mm, fs=FS_BODY)
    if data.run_id:
        _draw_kv(c, meta_x + 100 * mm, y1, tr("RUN_ID"), data.run_id, label_w=16 * mm, fs=FS_BODY)
    car_parts = [p for p in (_safe(data.car.name, ""), _safe(data.car.car_type, "")) if p]
    car_text = " \u2014 ".join(car_parts) if car_parts else na
    _draw_kv(c, meta_x, y2, tr("CAR_LABEL"), car_text, label_w=12 * mm, fs=FS_BODY)
    if data.start_time_utc:
        _draw_kv(
            c, meta_x, y3, tr("START_TIME_UTC"), data.start_time_utc, label_w=22 * mm, fs=FS_BODY
        )
    if data.end_time_utc:
        _draw_kv(c, meta_x, y4, tr("END_TIME_UTC"), data.end_time_utc, label_w=22 * mm, fs=FS_BODY)

    # Duration / sensor count on the right side, plus sensor/tire metadata
    meta_right = meta_x + 100 * mm
    extra_parts: list[str] = []
    if data.duration_text:
        extra_parts.append(f"{tr('DURATION')}: {data.duration_text}")
    if data.sensor_count:
        extra_parts.append(f"{tr('SENSORS_LABEL')}: {data.sensor_count}")
    if data.sensor_locations:
        extra_parts.append(", ".join(data.sensor_locations[:6]))
    if data.sample_count:
        extra_parts.append(f"{tr('SAMPLE_COUNT_LABEL')}: {data.sample_count}")
    if data.sample_rate_hz:
        extra_parts.append(f"{tr('RAW_SAMPLE_RATE_HZ_LABEL')}: {data.sample_rate_hz}")
    if extra_parts:
        c.setFillColor(_hex(MUTED_CLR))
        c.setFont(FONT, FS_BODY)
        c.drawString(meta_right, y2, " \u00b7 ".join(extra_parts))
    if data.sensor_model:
        _draw_kv(
            c, meta_right, y3, tr("SENSOR_MODEL"), data.sensor_model, label_w=24 * mm, fs=FS_BODY
        )
    if data.firmware_version:
        firmware_label = "Firmwareversie" if data.lang == "nl" else "Firmware Version"
        _draw_kv(
            c,
            meta_right,
            y4,
            firmware_label,
            data.firmware_version,
            label_w=24 * mm,
            fs=FS_BODY,
        )
    if data.tire_spec_text:
        _draw_kv(
            c, meta_right, y5, tr("TIRE_SIZE"), data.tire_spec_text, label_w=14 * mm, fs=FS_BODY
        )

    y_cursor = hdr_y - GAP

    # -- Observed signature (full-width) --
    obs_h = 34 * mm
    obs_y = y_cursor - obs_h

    # Observed Signature
    _draw_panel(c, m, obs_y, W, obs_h, tr("OBSERVED_SIGNATURE"))
    ox = m + 4 * mm
    oy = obs_y + obs_h - 10.5 * mm
    step = 4.5 * mm
    lw = OBSERVED_LABEL_W

    _draw_kv(c, ox, oy, tr("PRIMARY_SYSTEM"), _safe(data.observed.primary_system, na), label_w=lw)
    oy -= step
    _draw_kv(
        c,
        ox,
        oy,
        tr("STRONGEST_SENSOR"),
        _safe(data.observed.strongest_sensor_location, na),
        label_w=lw,
    )
    oy -= step
    _draw_kv(c, ox, oy, tr("SPEED_BAND"), _safe(data.observed.speed_band, na), label_w=lw)
    oy -= step
    _draw_kv(c, ox, oy, tr("STRENGTH"), _safe(data.observed.strength_label, na), label_w=lw)
    oy -= step

    cert_val = _safe(data.observed.certainty_label, na)
    if data.observed.certainty_pct:
        cert_val = f"{cert_val} ({data.observed.certainty_pct})"
    _draw_kv(c, ox, oy, tr("CERTAINTY_LABEL_FULL"), cert_val, label_w=lw)
    oy -= step
    if data.observed.certainty_reason:
        _draw_kv(c, ox, oy, tr("CERTAINTY_REASON"), data.observed.certainty_reason, label_w=lw)

    # Disclaimer
    disc_text = tr("PATTERN_SUGGESTION_DISCLAIMER")
    _draw_text(
        c, ox, obs_y + DISCLAIMER_Y_OFFSET, W - 8 * mm, disc_text, size=FS_SMALL, color=MUTED_CLR
    )

    y_cursor = obs_y - GAP

    # -- Systems with findings panel --
    cards = data.system_cards[:2]
    n_cards = len(cards) if cards else 0
    cards_h = 64 * mm
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
    next_h = 42 * mm
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
    if data.data_trust:
        for item in data.data_trust[:6]:
            icon = "\u2713" if item.state == "pass" else "\u26a0"
            state_lbl = tr("PASS") if item.state == "pass" else tr("WARN_SHORT")
            value = f"{icon} {state_lbl}"
            if item.state != "pass" and item.detail:
                value = f"{icon} {item.detail}"
            _draw_kv(
                c,
                tx,
                ty,
                item.check,
                value,
                label_w=DATA_TRUST_LABEL_W,
                fs=FS_SMALL,
            )
            ty -= DATA_TRUST_LINE_STEP
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
    """Draw ordered next-steps rows."""
    row_h = 6.6 * mm
    col1_w = 12 * mm

    y = y_top
    for idx, step in enumerate(steps[:5], start=1):
        if y - row_h < y_bottom:
            break
        bg = SOFT_BG if idx % 2 == 0 else PANEL_BG
        c.setFillColor(_hex(bg))
        c.setStrokeColor(_hex(LINE_CLR))
        c.rect(x, y - row_h, w, row_h, stroke=1, fill=1)

        c.setFillColor(_hex(TEXT_CLR))
        c.setFont(FONT_B, 7)
        c.drawString(x + 2, y - 4.4 * mm, f"{idx}.")

        action_text = step.action
        if step.why:
            action_text += f" \u2014 {step.why}"
        _draw_text(
            c,
            x + col1_w,
            y - 2 * mm,
            w - col1_w - 4,
            action_text,
            font=FONT,
            size=7,
            color=TEXT_CLR,
            max_lines=1,
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
    step = 4.0 * mm
    lw = 32 * mm

    systems_text = ", ".join(ev.matched_systems) if ev.matched_systems else na
    _draw_kv(c, rx, ry, tr("MATCHED_SYSTEMS"), systems_text, label_w=lw, fs=7)
    ry -= step
    _draw_kv(c, rx, ry, tr("STRONGEST_SENSOR"), _safe(ev.strongest_location, na), label_w=lw, fs=7)
    ry -= step
    _draw_kv(c, rx, ry, tr("SPEED_BAND"), _safe(ev.speed_band, na), label_w=lw, fs=7)
    ry -= step
    _draw_kv(c, rx, ry, tr("STRENGTH"), _safe(ev.strength_label, na), label_w=lw, fs=7)
    ry -= step

    cert_val = _safe(ev.certainty_label, na)
    if ev.certainty_pct:
        cert_val = f"{cert_val} ({ev.certainty_pct})"
    if ev.certainty_reason:
        cert_val = f"{cert_val} \u2014 {ev.certainty_reason}"
    _draw_kv(c, rx, ry, tr("CERTAINTY_LABEL_FULL"), cert_val, label_w=lw, fs=7)
    ry -= step * 1.4

    # Warning
    if ev.warning:
        c.setFillColor(_hex(WARN_CLR))
        c.setFont(FONT_B, FS_SMALL)
        c.drawString(rx, ry, f"\u26a0 {tr('WARNING_LABEL')}")
        ry -= 3.4 * mm
        ry = _draw_text(c, rx, ry, w - 8 * mm, ev.warning, size=6, color=WARN_CLR, max_lines=1)
        ry -= 2 * mm

    # Interpretation
    c.setFillColor(_hex(TEXT_CLR))
    c.setFont(FONT_B, FS_SMALL)
    c.drawString(rx, ry, tr("INTERPRETATION"))
    ry -= 3.6 * mm
    ry = _draw_text(
        c, rx, ry, w - 8 * mm, _safe(ev.interpretation, na), size=6, color=SUB_CLR, max_lines=2
    )
    ry -= 2 * mm

    # Why parts listed
    c.setFillColor(_hex(TEXT_CLR))
    c.setFont(FONT_B, FS_SMALL)
    c.drawString(rx, ry, tr("WHY_PARTS_LISTED"))
    ry -= 3.4 * mm
    _draw_text(
        c, rx, ry, w - 8 * mm, _safe(ev.why_parts_text, na), size=6, color=SUB_CLR, max_lines=3
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
        (tr("RANK"), 14 * mm),
        (tr("SYSTEM"), 30 * mm),
        (tr("FREQUENCY_HZ"), 22 * mm),
        (tr("ORDER_LABEL"), 28 * mm),
        (tr("AMP_G"), 20 * mm),
        (tr("SPEED_BAND"), 28 * mm),
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
            row.speed_band,
            row.relevance,
        ]
        for val, (_, cw) in zip(vals, col_defs, strict=True):
            c.drawString(cx_off, y - 4.2 * mm, val)
            cx_off += cw


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
    location_rows, _, _, _ = location_hotspots(
        summary.get("samples", []),
        findings,
        tr=tr_fn,
        text_fn=text_fn,
    )
    top_causes = [c for c in summary.get("top_causes", []) if isinstance(c, dict)]

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
