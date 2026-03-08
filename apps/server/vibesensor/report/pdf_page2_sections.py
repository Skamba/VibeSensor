"""Section renderers used by the page-2 evidence composition."""

from __future__ import annotations

from collections.abc import Callable

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from .pdf_diagram_render import car_location_diagram
from .pdf_drawing import _draw_panel, _hex
from .pdf_layout import assert_aspect_preserved, fit_rect_preserve_aspect
from .pdf_page_layouts import build_page2_layout
from .pdf_style import CAR_PANEL_TITLE_RESERVE, FONT_B, GAP, MARGIN, PAGE_H, SOFT_BG, TEXT_CLR
from .report_data import NextStep, ReportTemplateData
from .theme import BMW_LENGTH_MM as _BMW_LENGTH_MM
from .theme import BMW_WIDTH_MM as _BMW_WIDTH_MM


def render_title_bar(c: Canvas, *, title: str, width: float, page_top: float) -> float:
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
    return layout.title_bar.y - GAP


def render_car_visual_panel(
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
        top_causes or (findings if isinstance(findings, list) else []),
        render_summary,
        location_rows,
        content_width=content_width,
        tr=tr_fn,
        text_fn=text_fn,
        diagram_width=box_w,
        diagram_height=box_h,
    )
    diagram.drawOn(c, box_x, box_y)


def render_peaks_panel(
    c: Canvas,
    data: ReportTemplateData,
    *,
    tr: Callable[[str], str],
    layout,
    draw_peaks_table: Callable[..., None],
) -> None:
    _draw_panel(
        c,
        layout.peaks_panel.x,
        layout.peaks_panel.y,
        layout.peaks_panel.w,
        layout.peaks_panel.h,
        tr("DIAGNOSTIC_PEAKS"),
    )
    draw_peaks_table(
        c,
        layout.peaks_panel.x + 4 * mm,
        layout.peaks_panel.y + layout.peaks_panel.h - 10 * mm,
        layout.peaks_panel.w - 8 * mm,
        layout.peaks_panel.y + 3 * mm,
        data,
        tr,
    )


def render_observations_panel(
    c: Canvas,
    *,
    layout,
    transient_findings: list[dict[str, object]],
    tr: Callable[[str], str],
    draw_additional_observations: Callable[..., None],
) -> float:
    if layout.observations_panel is None:
        return layout.peaks_panel.y
    draw_additional_observations(
        c,
        layout.observations_panel.x,
        layout.observations_panel.y,
        layout.observations_panel.w,
        layout.observations_panel.h,
        transient_findings,
        tr,
    )
    return layout.observations_panel.y


def render_continued_next_steps_panel(
    c: Canvas,
    *,
    panel,
    next_steps_continued: list[NextStep],
    start_number: int,
    tr: Callable[[str], str],
    draw_next_steps_table: Callable[..., int],
) -> None:
    _draw_panel(c, panel.x, panel.y, panel.w, panel.h, tr("NEXT_STEPS"))
    draw_next_steps_table(
        c,
        panel.x + 4 * mm,
        panel.y + panel.h - 11 * mm,
        panel.w - 8 * mm,
        panel.y + 3 * mm,
        next_steps_continued,
        start_number=start_number,
    )
