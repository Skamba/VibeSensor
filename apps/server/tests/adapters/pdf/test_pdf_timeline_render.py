"""Focused tests for the page-1 run timeline graph renderer."""

from __future__ import annotations

from reportlab.graphics.shapes import Circle, PolyLine, Rect, String

from vibesensor.adapters.pdf.pdf_drawing import _hex
from vibesensor.adapters.pdf.pdf_style import REPORT_COLORS
from vibesensor.adapters.pdf.pdf_timeline_render import run_timeline_graph
from vibesensor.adapters.pdf.report_data import TimelineGraphData, TimelineGraphInterval


def _color_hex(color: object) -> str | None:
    return color.hexval() if color is not None else None


def test_run_timeline_graph_draws_speed_line_evidence_and_labels() -> None:
    drawing = run_timeline_graph(
        TimelineGraphData(
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
        ),
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
