"""Pattern-evidence panel helpers for PDF page 2."""

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
    FONT_B,
    FS_SMALL,
    PANEL_HEADER_H,
    SUB_CLR,
    WARN_CLR,
)
from vibesensor.adapters.pdf.pdf_text import _draw_kv, _draw_section_block, _draw_text
from vibesensor.adapters.pdf.report_data import PatternEvidence


def _draw_pattern_evidence(
    c: Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    ev: PatternEvidence,
    tr: Callable[[str], str],
) -> None:
    """Draw the pattern-evidence panel on page 2."""
    na = tr("NOT_AVAILABLE")

    _draw_panel(c, x, y, w, h, tr("PATTERN_EVIDENCE"))
    rx = x + 4 * mm
    ry = y + h - PANEL_HEADER_H
    label_w = 28 * mm
    val_w = w - 8 * mm - label_w

    systems_text = ", ".join(ev.matched_systems) if ev.matched_systems else na
    ry = _draw_kv(
        c,
        rx,
        ry,
        tr("MATCHED_SYSTEMS"),
        systems_text,
        label_w=label_w,
        fs=7,
        value_w=val_w,
    )
    ry -= 1.0 * mm
    ry = _draw_kv(
        c,
        rx,
        ry,
        tr("STRONGEST_SENSOR"),
        _safe(ev.strongest_location, na),
        label_w=label_w,
        fs=7,
    )
    ry -= 1.0 * mm
    ry = _draw_kv(c, rx, ry, tr("SPEED_BAND"), _safe(ev.speed_band, na), label_w=label_w, fs=7)
    ry -= 1.0 * mm
    ry = _draw_kv(
        c,
        rx,
        ry,
        tr("STRENGTH"),
        _strength_with_peak(
            ev.strength_label,
            ev.strength_peak_db,
            fallback=na,
            peak_suffix=tr("STRENGTH_PEAK_SUFFIX"),
        ),
        label_w=label_w,
        fs=7,
        value_w=val_w,
    )
    ry -= 1.0 * mm

    cert_val = _cert_display(ev.certainty_label, ev.certainty_pct, na)
    ry = _draw_kv(c, rx, ry, tr("CERTAINTY_LABEL_FULL"), cert_val, label_w=label_w, fs=7)
    ry -= 0.5 * mm
    if ev.certainty_reason:
        ry = _draw_text(
            c,
            rx + 2 * mm,
            ry,
            val_w + label_w - 2 * mm,
            ev.certainty_reason,
            size=FS_SMALL,
            color=SUB_CLR,
            max_lines=3,
        )
    ry -= 2.0 * mm

    if ev.warning:
        c.setFillColor(_hex(WARN_CLR))
        c.setFont(FONT_B, FS_SMALL)
        c.drawString(rx, ry, f"⚠ {tr('WARNING_LABEL')}")
        ry -= 3.0 * mm
        ry = _draw_text(
            c,
            rx,
            ry,
            w - 8 * mm,
            ev.warning,
            size=FS_SMALL,
            color=WARN_CLR,
            max_lines=4,
        )
        ry -= 1.5 * mm

    ry = _draw_section_block(
        c,
        rx,
        ry,
        w - 8 * mm,
        tr("INTERPRETATION"),
        _safe(ev.interpretation, na),
        max_lines=5,
    )
    _draw_section_block(
        c,
        rx,
        ry,
        w - 8 * mm,
        tr("WHY_PARTS_LISTED"),
        _safe(ev.why_parts_text, na),
        title_gap=3.0 * mm,
        max_lines=5,
    )
