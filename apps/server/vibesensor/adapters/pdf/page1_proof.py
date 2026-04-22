"""Proof and timeline rendering for report page 1."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from vibesensor.adapters.pdf.page1_common import draw_label_value
from vibesensor.adapters.pdf.pdf_diagram_render import car_location_diagram
from vibesensor.adapters.pdf.pdf_drawing import _draw_panel
from vibesensor.adapters.pdf.pdf_style import (
    FONT_B,
    FS_BODY,
    FS_H2,
    FS_SMALL,
    PANEL_HEADER_H,
    SUB_CLR,
    TEXT_CLR,
)
from vibesensor.adapters.pdf.pdf_text import _draw_text, _wrap_lines
from vibesensor.adapters.pdf.pdf_timeline_render import run_timeline_graph

if TYPE_CHECKING:
    from vibesensor.adapters.pdf.report_types import Page1RenderPlan

__all__ = ["draw_proof_block", "draw_timeline_block"]


def draw_proof_block(
    c: Canvas,
    plan: Page1RenderPlan,
    *,
    tr: Callable[..., str],
    x: float,
    y: float,
    w: float,
    h: float,
) -> None:
    verdict = plan.verdict_page
    _draw_panel(c, x, y, w, h, verdict.proof_panel_title or tr("REPORT_PROOF_PANEL_TITLE"))
    inner_x = x + 4 * mm
    inner_y = y + h - PANEL_HEADER_H - 2 * mm
    diagram_w = w * 0.44
    left_x = inner_x
    left_w = diagram_w - 2 * mm
    left_bottom = y + 7 * mm
    left_top = inner_y
    left_content_h = left_top - left_bottom
    diagram_y = left_bottom + (4 * mm)
    diagram_h = left_content_h - (4 * mm)
    diagram = car_location_diagram(
        plan.top_causes or plan.findings,
        {
            "sensor_locations": plan.sensor_locations,
            "sensor_intensity_by_location": plan.sensor_intensity_by_location,
        },
        plan.location_hotspot_rows,
        content_width=w - 8 * mm,
        tr=tr,
        diagram_width=left_w,
        diagram_height=diagram_h - 2 * mm,
        vertical_align="top",
    )
    diagram.drawOn(c, left_x, diagram_y)

    text_x = x + diagram_w + 5 * mm
    text_w = w - diagram_w - 9 * mm
    text_y = inner_y
    text_y = (
        _draw_text(
            c,
            text_x,
            text_y,
            text_w,
            verdict.proof_summary or tr("UNKNOWN"),
            font=FONT_B,
            size=FS_BODY,
            color=TEXT_CLR,
            leading=FS_BODY + 1.4,
            max_lines=4,
        )
        - 1.5 * mm
    )
    for snapshot in verdict.proof_snapshot_rows[:3]:
        text_y = draw_label_value(
            c,
            x=text_x,
            y=text_y,
            width=text_w,
            label=snapshot.label,
            value=snapshot.value or tr("UNKNOWN"),
            value_size=FS_BODY,
            max_lines=3,
        )
    text_y = draw_label_value(
        c,
        x=text_x,
        y=text_y,
        width=text_w,
        label=tr("REPORT_DOMINANT_CORNER_LABEL"),
        value=verdict.dominant_corner or tr("UNKNOWN"),
        value_size=FS_H2,
    )
    if verdict.runner_up_corner:
        text_y = draw_label_value(
            c,
            x=text_x,
            y=text_y,
            width=text_w,
            label=tr("REPORT_RUNNER_UP_CORNER_LABEL"),
            value=verdict.runner_up_corner,
            value_size=FS_BODY,
        )
    location_confidence = verdict.location_confidence or tr("UNKNOWN")
    confidence_value_size = (
        FS_BODY if len(_wrap_lines(location_confidence, text_w, FS_H2)) > 1 else FS_H2
    )
    confidence_max_lines = 3 if confidence_value_size == FS_BODY else 2
    text_y = draw_label_value(
        c,
        x=text_x,
        y=text_y,
        width=text_w,
        label=tr("REPORT_LOCATION_CONFIDENCE_LABEL"),
        value=location_confidence,
        value_size=confidence_value_size,
        max_lines=confidence_max_lines,
    )
    text_y = draw_label_value(
        c,
        x=text_x,
        y=text_y,
        width=text_w,
        label=tr("REPORT_COVERAGE_LABEL"),
        value=verdict.coverage_label or tr("UNKNOWN"),
        value_size=FS_BODY,
        max_lines=3,
    )
    if verdict.also_consider:
        text_y = draw_label_value(
            c,
            x=text_x,
            y=text_y,
            width=text_w,
            label=tr("REPORT_ALTERNATIVE_SOURCE_LABEL"),
            value=verdict.also_consider,
            value_size=FS_BODY,
        )
    if verdict.proof_caveat:
        _draw_text(
            c,
            text_x,
            text_y - 1.5 * mm,
            text_w,
            verdict.proof_caveat,
            size=FS_SMALL,
            color=SUB_CLR,
            leading=FS_SMALL + 1.2,
        )


def draw_timeline_block(
    c: Canvas,
    plan: Page1RenderPlan,
    *,
    tr: Callable[..., str],
    x: float,
    y: float,
    w: float,
    h: float,
) -> None:
    timeline_graph = plan.verdict_page.timeline_graph
    if timeline_graph is None:
        return

    _draw_panel(c, x, y, w, h, tr("REPORT_TIMELINE_TITLE"))
    graph_x = x + 4 * mm
    graph_y = y + 4 * mm
    graph_w = w - 8 * mm
    graph_h = h - PANEL_HEADER_H - 6 * mm
    run_timeline_graph(
        timeline_graph,
        tr=tr,
        graph_width=graph_w,
        graph_height=graph_h,
        show_title=False,
    ).drawOn(c, graph_x, graph_y)
