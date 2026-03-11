"""Page 2 composition for the evidence and diagnostics PDF page."""

from __future__ import annotations

import math
from collections.abc import Callable

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from ..report_i18n import tr as _tr
from .pdf_diagram_render import car_location_diagram
from .pdf_drawing import _cert_display, _draw_panel, _hex, _norm, _safe, _strength_with_peak
from .pdf_page_layouts import build_page2_layout
from .pdf_render_context import PdfRenderContext
from .pdf_style import (
    CAR_PANEL_TITLE_RESERVE,
    FONT,
    FONT_B,
    FS_SMALL,
    GAP,
    LINE_CLR,
    MARGIN,
    MUTED_CLR,
    PAGE_H,
    PAGE_W,
    PANEL_BG,
    PANEL_HEADER_H,
    SOFT_BG,
    SUB_CLR,
    TEXT_CLR,
    WARN_CLR,
)
from .pdf_text import _draw_kv, _draw_section_block, _draw_text
from .report_data import NextStep, PatternEvidence, ReportTemplateData
from .theme import BMW_LENGTH_MM as _BMW_LENGTH_MM
from .theme import BMW_WIDTH_MM as _BMW_WIDTH_MM

# -- Aspect-ratio helpers (merged from pdf_layout) ----------------------------


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
    cross_src = src_w * drawn_h
    cross_drawn = drawn_w * src_h
    if abs(cross_drawn - cross_src) > tolerance * cross_src:
        src_ratio = src_w / src_h
        drawn_ratio = drawn_w / drawn_h
        delta = abs(drawn_ratio - src_ratio) / src_ratio
        raise AssertionError(
            f"Car visual aspect ratio distorted. src={src_ratio:.4f}, "
            f"drawn={drawn_ratio:.4f}, delta={delta:.2%}",
        )


# -- Section helpers (merged from pdf_page2_sections) -------------------------


def _draw_title_bar(c: Canvas, *, title: str, width: float, page_top: float) -> float:
    layout = build_page2_layout(
        width=width,
        page_top=page_top,
        has_transient_findings=False,
        has_next_steps_continued=False,
    )
    _draw_panel(
        c,
        layout.title_bar.x,
        layout.title_bar.y,
        layout.title_bar.w,
        layout.title_bar.h,
        fill=SOFT_BG,
    )
    c.setFillColor(_hex(TEXT_CLR))
    c.setFont(FONT_B, 11)
    c.drawString(MARGIN + 4 * mm, layout.title_bar.y + 3.5 * mm, title)
    return layout.title_bar.y - GAP  # type: ignore[no-any-return]


def _draw_car_visual_panel(
    c: Canvas,
    data: ReportTemplateData,
    *,
    tr_fn: Callable[..., str],
    text_fn: Callable[[str, str], str],
    x: float,
    y: float,
    w: float,
    h: float,
    location_rows: list,
    top_causes: list,
    content_width: float,
) -> None:
    _draw_panel(c, x, y, w, h, tr_fn("EVIDENCE_AND_HOTSPOTS"))
    layout = build_page2_layout(
        width=content_width,
        page_top=PAGE_H - MARGIN,
        has_transient_findings=False,
        has_next_steps_continued=False,
    )
    car_layout = layout.car_panel
    box_x = car_layout.box_x if x == MARGIN else x + 5 * mm
    box_y = car_layout.box_y if x == MARGIN else y + 5 * mm
    box_w = car_layout.box_w if x == MARGIN else w - 10 * mm
    box_h = car_layout.box_h if x == MARGIN else h - CAR_PANEL_TITLE_RESERVE

    src_w = _BMW_WIDTH_MM
    src_h = _BMW_LENGTH_MM
    _dx, _dy, draw_w, draw_h = fit_rect_preserve_aspect(src_w, src_h, box_x, box_y, box_w, box_h)
    assert_aspect_preserved(src_w, src_h, draw_w, draw_h, tolerance=0.03)

    render_summary = {
        "sensor_locations": data.sensor_locations,
        "sensor_intensity_by_location": data.sensor_intensity_by_location,
    }
    findings = data.findings
    diagram = car_location_diagram(
        top_causes or (findings if isinstance(findings, list) else []),  # type: ignore[arg-type]
        render_summary,
        location_rows,
        content_width=content_width,
        tr=tr_fn,
        text_fn=text_fn,
        diagram_width=box_w,
        diagram_height=box_h,
    )
    diagram.drawOn(c, box_x, box_y)


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
            max_lines=2,
        )
    ry -= 2.0 * mm

    if ev.warning:
        c.setFillColor(_hex(WARN_CLR))
        c.setFont(FONT_B, FS_SMALL)
        c.drawString(rx, ry, f"\u26a0 {tr('WARNING_LABEL')}")
        ry -= 3.0 * mm
        ry = _draw_text(
            c,
            rx,
            ry,
            w - 8 * mm,
            ev.warning,
            size=FS_SMALL,
            color=WARN_CLR,
            max_lines=3,
        )
        ry -= 1.5 * mm

    ry = _draw_section_block(
        c,
        rx,
        ry,
        w - 8 * mm,
        tr("INTERPRETATION"),
        _safe(ev.interpretation, na),
    )
    _draw_section_block(
        c,
        rx,
        ry,
        w - 8 * mm,
        tr("WHY_PARTS_LISTED"),
        _safe(ev.why_parts_text, na),
        title_gap=3.0 * mm,
    )


def _draw_peaks_table(
    c: Canvas,
    x: float,
    y_top: float,
    w: float,
    y_bottom: float,
    data: ReportTemplateData,
    tr: Callable[[str], str],
) -> None:
    """Diagnostic-first peaks table."""
    col_defs = [
        (tr("RANK"), 12 * mm),
        (tr("SYSTEM"), 24 * mm),
        (tr("FREQUENCY_HZ"), 18 * mm),
        (tr("ORDER_LABEL"), 24 * mm),
        (tr("PEAK_DB"), 18 * mm),
        (tr("STRENGTH_DB"), 16 * mm),
        (tr("SPEED_BAND"), 22 * mm),
    ]
    used = sum(col_w for _, col_w in col_defs)
    notes_w = max(20 * mm, w - used)
    col_defs.append((tr("RELEVANCE"), notes_w))

    row_h = 6.2 * mm
    y = y_top

    c.setFillColor(_hex(SOFT_BG))
    c.setStrokeColor(_hex(LINE_CLR))
    c.rect(x, y - row_h + 1, w, row_h, stroke=1, fill=1)
    c.setFillColor(_hex(SUB_CLR))
    c.setFont(FONT_B, 6.5)
    cx_off = x + 1.5
    for label, col_w in col_defs:
        c.drawString(cx_off, y - 4.2 * mm, label)
        cx_off += col_w

    c.setFont(FONT, 6.5)
    rows = data.peak_rows
    if not rows:
        y -= row_h
        c.setFillColor(_hex(PANEL_BG))
        c.rect(x, y - row_h + 1, w, row_h, stroke=1, fill=1)
        c.setFillColor(_hex(MUTED_CLR))
        c.drawString(x + 2, y - 4.2 * mm, "\u2014")
        return

    soft_bg = _hex(SOFT_BG)
    panel_bg = _hex(PANEL_BG)
    text_clr = _hex(TEXT_CLR)
    y_off = 4.2 * mm
    for idx, row in enumerate(rows, start=1):
        y -= row_h
        if y - row_h < y_bottom:
            break
        c.setFillColor(soft_bg if idx % 2 == 0 else panel_bg)
        c.rect(x, y - row_h + 1, w, row_h, stroke=1, fill=1)
        c.setFillColor(text_clr)
        cx_off = x + 1.5
        row_y = y - y_off
        for value, (_, col_w) in zip(
            (
                row.rank,
                row.system,
                row.freq_hz,
                row.order,
                row.peak_db,
                row.strength_db,
                row.speed_band,
                row.relevance,
            ),
            col_defs,
            strict=True,
        ):
            c.drawString(cx_off, row_y, value)
            cx_off += col_w


def _draw_additional_observations(
    c: Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    transient_findings: list[dict[str, object]],
    tr: Callable[[str], str],
) -> None:
    """Draw transient-impact findings in the additional-observations panel."""
    _draw_panel(c, x, y, w, h, tr("ADDITIONAL_OBSERVATIONS"), fill=SOFT_BG)
    c.setFillColor(_hex(MUTED_CLR))
    c.setFont(FONT, 6.5)

    isfinite = math.isfinite
    x_pad = x + 4 * mm
    step = 3.5 * mm
    y_min = y + 2 * mm
    y_cursor = y + h - 10 * mm
    for finding in transient_findings[:3]:
        if y_cursor < y_min:
            break
        order_label = str(finding.get("frequency_hz_or_order") or "").strip()
        if not order_label:
            order_label = tr("SOURCE_TRANSIENT_IMPACT")
        try:
            confidence = float(finding.get("confidence_0_to_1") or 0.0)  # type: ignore[arg-type]
        except (ValueError, TypeError):
            confidence = 0.0
        if not isfinite(confidence):
            confidence = 0.0
        c.drawString(x_pad, y_cursor, f"\u2022 {order_label} ({confidence * 100.0:.0f}%)")
        y_cursor -= step


def _draw_continued_next_steps(
    c: Canvas,
    *,
    y_top: float,
    next_steps_continued: list[NextStep],
    start_number: int,
    tr: Callable[[str], str],
) -> None:
    layout = build_page2_layout(
        width=PAGE_W - 2 * MARGIN,
        page_top=PAGE_H - MARGIN,
        has_transient_findings=y_top < (PAGE_H - MARGIN),
        has_next_steps_continued=True,
    )
    if layout.continued_next_steps is None:
        return
    from .pdf_page1 import _draw_next_steps_table

    panel = layout.continued_next_steps
    _draw_panel(c, panel.x, panel.y, panel.w, panel.h, tr("NEXT_STEPS"))
    _draw_next_steps_table(
        c,
        panel.x + 4 * mm,
        panel.y + panel.h - 11 * mm,
        panel.w - 8 * mm,
        panel.y + 3 * mm,
        next_steps_continued,
        start_number=start_number,
    )


def _page2(
    c: Canvas,
    data: ReportTemplateData,
    *,
    ctx: PdfRenderContext | None = None,
    next_steps_continued: list[NextStep] | None = None,
) -> None:
    """Render page-2: car visual, pattern evidence, and peaks table."""
    render_ctx = ctx or PdfRenderContext.from_data(data)
    width = render_ctx.width
    page_top = render_ctx.page_top

    def tr(key: str) -> str:
        return _tr(data.lang, key)

    transient_findings = [
        finding
        for finding in data.findings
        if isinstance(finding, dict)
        and _norm(finding.get("severity")) == "info"
        and (
            _norm(finding.get("suspected_source")) == "transient_impact"
            or _norm(finding.get("peak_classification")) == "transient"
        )
    ]
    layout = build_page2_layout(
        width=width,
        page_top=page_top,
        has_transient_findings=bool(transient_findings),
        has_next_steps_continued=bool(next_steps_continued),
    )

    _draw_title_bar(c, title=tr("EVIDENCE_DIAGNOSTICS"), width=width, page_top=page_top)

    _draw_car_visual_panel(
        c,
        data,
        tr_fn=render_ctx.tr_fn,
        text_fn=render_ctx.text_fn,
        x=layout.car_panel.panel.x,
        y=layout.car_panel.panel.y,
        w=layout.car_panel.panel.w,
        h=layout.car_panel.panel.h,
        location_rows=render_ctx.location_rows,
        top_causes=render_ctx.top_causes,
        content_width=width,
    )
    _draw_pattern_evidence(
        c,
        layout.pattern_panel.x,
        layout.pattern_panel.y,
        layout.pattern_panel.w,
        layout.pattern_panel.h,
        data.pattern_evidence,
        tr,
    )

    _draw_panel(
        c,
        layout.peaks_panel.x,
        layout.peaks_panel.y,
        layout.peaks_panel.w,
        layout.peaks_panel.h,
        tr("DIAGNOSTIC_PEAKS"),
    )
    _draw_peaks_table(
        c,
        layout.peaks_panel.x + 4 * mm,
        layout.peaks_panel.y + layout.peaks_panel.h - 10 * mm,
        layout.peaks_panel.w - 8 * mm,
        layout.peaks_panel.y + 3 * mm,
        data,
        tr,
    )

    if layout.observations_panel is not None:
        _draw_additional_observations(
            c,
            layout.observations_panel.x,
            layout.observations_panel.y,
            layout.observations_panel.w,
            layout.observations_panel.h,
            transient_findings,  # type: ignore[arg-type]
            tr,
        )
        obs_y = layout.observations_panel.y
    else:
        obs_y = layout.peaks_panel.y

    if next_steps_continued:
        page1_drawn = len(data.next_steps) - len(next_steps_continued)
        _draw_continued_next_steps(
            c,
            y_top=obs_y - GAP,
            next_steps_continued=next_steps_continued,
            start_number=page1_drawn + 1,
            tr=tr,
        )
