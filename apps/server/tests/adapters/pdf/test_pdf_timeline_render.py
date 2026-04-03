"""Focused tests for the page-1 run timeline graph renderer."""

from __future__ import annotations

from reportlab.graphics.shapes import Circle, PolyLine, Rect, String

from vibesensor.adapters.pdf.models import TimelineGraphData, TimelineGraphInterval
from vibesensor.adapters.pdf.pdf_drawing import _hex
from vibesensor.adapters.pdf.pdf_style import REPORT_COLORS
from vibesensor.adapters.pdf.pdf_timeline_render import run_timeline_graph


def _color_hex(color: object) -> str | None:
    return color.hexval() if color is not None else None


def _sample_timeline_graph() -> TimelineGraphData:
    return TimelineGraphData(
        duration_s=12.0,
        speed_ceiling_kmh=80.0,
        intervals=(
            TimelineGraphInterval(
                phase_label="cruise",
                start_t_s=0.0,
                end_t_s=4.0,
                speed_min_kmh=58.0,
                speed_max_kmh=63.0,
                has_fault_evidence=False,
            ),
            TimelineGraphInterval(
                phase_label="cruise",
                start_t_s=4.0,
                end_t_s=9.0,
                speed_min_kmh=64.0,
                speed_max_kmh=72.0,
                has_fault_evidence=True,
            ),
        ),
    )


def _plot_rect(drawing: object) -> Rect:
    return next(
        item
        for item in getattr(drawing, "contents", [])
        if isinstance(item, Rect)
        and _color_hex(item.fillColor) == _hex(REPORT_COLORS["surface"]).hexval()
        and _color_hex(item.strokeColor) == _hex(REPORT_COLORS["border"]).hexval()
    )


def test_run_timeline_graph_draws_speed_line_evidence_and_labels() -> None:
    drawing = run_timeline_graph(
        _sample_timeline_graph(),
        tr=lambda key, **_kw: key,
        graph_width=140.0,
        graph_height=96.0,
    )

    strings = [item.text for item in drawing.contents if isinstance(item, String)]

    assert "REPORT_TIMELINE_TITLE" in strings
    assert "REPORT_TIMELINE_SPEED_LABEL" in strings
    assert "REPORT_TIMELINE_DETECTIONS_LABEL" in strings
    assert any(
        isinstance(item, PolyLine)
        and _color_hex(item.strokeColor) == _hex(REPORT_COLORS["brand"]).hexval()
        for item in drawing.contents
    )
    assert any(
        isinstance(item, Rect)
        and _color_hex(item.fillColor) == _hex(REPORT_COLORS["card_error_bg"]).hexval()
        for item in drawing.contents
    )
    assert any(
        isinstance(item, Circle)
        and _color_hex(item.fillColor) == _hex(REPORT_COLORS["danger"]).hexval()
        for item in drawing.contents
    )


def test_run_timeline_graph_keeps_detection_windows_in_a_dedicated_lane() -> None:
    drawing = run_timeline_graph(
        _sample_timeline_graph(),
        tr=lambda key, **_kw: key,
        graph_width=180.0,
        graph_height=96.0,
    )

    plot_rect = _plot_rect(drawing)
    detection_rects = [
        item
        for item in drawing.contents
        if isinstance(item, Rect)
        and _color_hex(item.fillColor) == _hex(REPORT_COLORS["card_error_bg"]).hexval()
        and item.width < plot_rect.width
        and item.y < plot_rect.y + (plot_rect.height * 0.25)
    ]

    assert detection_rects
    assert all(rect.height < (plot_rect.height * 0.25) for rect in detection_rects)
    assert all(rect.y >= plot_rect.y for rect in detection_rects)
    assert all(
        rect.y + rect.height <= plot_rect.y + (plot_rect.height * 0.25) for rect in detection_rects
    )


def test_run_timeline_graph_keeps_title_and_legend_above_plot() -> None:
    drawing = run_timeline_graph(
        _sample_timeline_graph(),
        tr=lambda key, **_kw: key,
        graph_width=180.0,
        graph_height=96.0,
    )

    plot_rect = _plot_rect(drawing)
    strings = {item.text: item for item in drawing.contents if isinstance(item, String)}
    plot_top = plot_rect.y + plot_rect.height

    assert strings["REPORT_TIMELINE_TITLE"].y > plot_top + 8.0
    assert strings["REPORT_TIMELINE_SPEED_LABEL"].y > plot_top + 1.0
    assert strings["REPORT_TIMELINE_DETECTIONS_LABEL"].y > plot_top + 1.0


def test_run_timeline_graph_can_omit_internal_title_for_panel_usage() -> None:
    drawing = run_timeline_graph(
        _sample_timeline_graph(),
        tr=lambda key, **_kw: key,
        graph_width=240.0,
        graph_height=78.0,
        show_title=False,
    )

    strings = [item.text for item in drawing.contents if isinstance(item, String)]

    assert "REPORT_TIMELINE_TITLE" not in strings
    assert "REPORT_TIMELINE_SPEED_LABEL" in strings
    assert "REPORT_TIMELINE_DETECTIONS_LABEL" in strings
