"""Car-diagram panel helpers for PDF page 2."""

from __future__ import annotations

from collections.abc import Callable

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.shared.boundaries.reporting.document import FindingPresentation, ReportTemplateData
from vibesensor.adapters.pdf.pdf_diagram_render import car_location_diagram
from vibesensor.adapters.pdf.pdf_drawing import _draw_panel
from vibesensor.adapters.pdf.pdf_style import BMW_LENGTH_MM as _BMW_LENGTH_MM
from vibesensor.adapters.pdf.pdf_style import BMW_WIDTH_MM as _BMW_WIDTH_MM
from vibesensor.adapters.pdf.pdf_style import (
    CAR_PANEL_TITLE_RESERVE,
    FS_SMALL,
    MARGIN,
    PAGE_H,
    PANEL_HEADER_H,
    SUB_CLR,
    TEXT_CLR,
    build_page2_layout,
)
from vibesensor.adapters.pdf.pdf_text import _draw_text
from vibesensor.domain import LocationHotspotRow


def _hotspot_strength_text(data: ReportTemplateData, *, fallback: str) -> str:
    peak_db = data.pattern_evidence.strength_peak_db
    if peak_db is not None:
        return f"{peak_db:.0f} dB"
    if data.pattern_evidence.strength_label:
        return data.pattern_evidence.strength_label
    return fallback


def _hotspot_summary_text(
    data: ReportTemplateData, *, fallback: str, tr_fn: Callable[..., str]
) -> str:
    location = data.pattern_evidence.strongest_location or fallback
    strength = _hotspot_strength_text(data, fallback=fallback)
    certainty = data.pattern_evidence.certainty_label or fallback
    return f"{tr_fn('HOTSPOT_SUMMARY')}: {location} | {strength} | {certainty}"


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
    location_rows: list[LocationHotspotRow],
    top_causes: list[FindingPresentation],
    content_width: float,
) -> None:
    _draw_panel(c, x, y, w, h, tr_fn("EVIDENCE_AND_HOTSPOTS"))
    caption_x = x + 4 * mm
    caption_top = y + h - PANEL_HEADER_H - 1.5 * mm
    caption_w = w - 8 * mm
    caption_reserve = 11 * mm
    not_available = tr_fn("NOT_AVAILABLE")
    caption_bottom = _draw_text(
        c,
        caption_x,
        caption_top,
        caption_w,
        _hotspot_summary_text(data, fallback=not_available, tr_fn=tr_fn),
        size=FS_SMALL,
        color=TEXT_CLR,
        max_lines=2,
    )
    _draw_text(
        c,
        caption_x,
        caption_bottom - 0.4 * mm,
        caption_w,
        tr_fn("HOTSPOT_MARKER_SIZE_HINT"),
        size=FS_SMALL,
        color=SUB_CLR,
        max_lines=2,
    )
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
    box_y += caption_reserve
    box_h -= caption_reserve

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
        top_causes or findings,
        render_summary,
        location_rows,
        content_width=content_width,
        tr=tr_fn,
        text_fn=text_fn,
        diagram_width=box_w,
        diagram_height=box_h,
    )
    diagram.drawOn(c, box_x, box_y)
