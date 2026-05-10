"""Drawing assembly for the compact run timeline graph on report page 1."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from vibesensor.adapters.pdf.pdf_drawing import _hex
from vibesensor.adapters.pdf.pdf_style import FONT, FONT_B, FS_SMALL, REPORT_COLORS
from vibesensor.shared.boundaries.reporting.document import TimelineGraphData, TimelineGraphInterval

__all__ = ["run_timeline_graph"]


@dataclass(frozen=True, slots=True)
class _TimelineLayout:
    legend_y: float
    plot_x: float
    plot_y: float
    plot_w: float
    plot_h: float
    detection_lane_h: float
    detection_lane_gap: float
    speed_plot_y: float
    speed_plot_h: float


def _format_time_label(seconds: float) -> str:
    rounded = max(0, int(round(seconds)))
    minutes, secs = divmod(rounded, 60)
    if minutes:
        return f"{minutes}:{secs:02d}"
    return f"{secs}s"


def _x_for_time(*, t_s: float, plot_x: float, plot_w: float, duration_s: float) -> float:
    if duration_s <= 0:
        return plot_x
    bounded = min(max(t_s, 0.0), duration_s)
    return plot_x + ((bounded / duration_s) * plot_w)


def _speed_value(interval: TimelineGraphInterval) -> float | None:
    speeds = [
        speed for speed in (interval.speed_min_kmh, interval.speed_max_kmh) if speed is not None
    ]
    if not speeds:
        return None
    if len(speeds) == 1:
        return speeds[0]
    return (speeds[0] + speeds[1]) / 2.0


def _y_for_speed(
    *, speed_kmh: float, plot_y: float, plot_h: float, speed_ceiling_kmh: float
) -> float:
    if speed_ceiling_kmh <= 0:
        return plot_y
    bounded = min(max(speed_kmh, 0.0), speed_ceiling_kmh)
    return plot_y + ((bounded / speed_ceiling_kmh) * plot_h)


def _build_layout(*, graph_width: float, graph_height: float, show_title: bool) -> _TimelineLayout:
    top_cursor = graph_height - 4.0
    if show_title:
        top_cursor = top_cursor - 5.0 - 10.0
    legend_y = top_cursor - 1.0
    plot_x = 24.0
    plot_y = 12.0
    plot_w = max(72.0, graph_width - 30.0)
    plot_top = legend_y - 8.0
    plot_h = max(28.0, plot_top - plot_y)
    detection_lane_h = min(8.0, max(6.0, plot_h * 0.16))
    detection_lane_gap = 4.0
    speed_plot_y = plot_y + detection_lane_h + detection_lane_gap
    speed_plot_h = max(18.0, plot_h - detection_lane_h - detection_lane_gap)
    return _TimelineLayout(
        legend_y=legend_y,
        plot_x=plot_x,
        plot_y=plot_y,
        plot_w=plot_w,
        plot_h=plot_h,
        detection_lane_h=detection_lane_h,
        detection_lane_gap=detection_lane_gap,
        speed_plot_y=speed_plot_y,
        speed_plot_h=speed_plot_h,
    )


def run_timeline_graph(
    timeline_graph: TimelineGraphData,
    *,
    tr: Callable[..., str],
    graph_width: float,
    graph_height: float,
    show_title: bool = True,
) -> Any:
    """Build and return a ReportLab drawing for the proof-block run timeline."""
    from reportlab.graphics.shapes import Drawing

    drawing = Drawing(graph_width, graph_height)
    layout = _build_layout(
        graph_width=graph_width,
        graph_height=graph_height,
        show_title=show_title,
    )
    if show_title:
        _draw_timeline_title(drawing, tr=tr, graph_height=graph_height)
    _draw_timeline_legend(drawing, tr=tr, layout=layout)
    _draw_timeline_axes(drawing, timeline_graph=timeline_graph, layout=layout)
    _draw_timeline_intervals(drawing, timeline_graph=timeline_graph, layout=layout)
    return drawing


def _draw_timeline_title(drawing: Any, *, tr: Callable[..., str], graph_height: float) -> None:
    from reportlab.graphics.shapes import String

    top_cursor = graph_height - 4.0
    title_y = top_cursor - 5.0
    drawing.add(
        String(
            0.0,
            title_y,
            tr("REPORT_TIMELINE_TITLE"),
            fontName=FONT_B,
            fontSize=7.5,
            fillColor=_hex(REPORT_COLORS["text_primary"]),
        ),
    )


def _draw_timeline_legend(drawing: Any, *, tr: Callable[..., str], layout: _TimelineLayout) -> None:
    from reportlab.graphics.shapes import Circle, Line, Rect, String

    speed_legend_x = layout.plot_x + 2.0
    detection_legend_x = min(layout.plot_x + 78.0, layout.plot_x + layout.plot_w - 34.0)
    drawing.add(
        Line(
            speed_legend_x,
            layout.legend_y,
            speed_legend_x + 10.0,
            layout.legend_y,
            strokeColor=_hex(REPORT_COLORS["brand"]),
            strokeWidth=1.8,
        ),
    )
    drawing.add(
        String(
            speed_legend_x + 13.0,
            layout.legend_y - 2.6,
            tr("REPORT_TIMELINE_SPEED_LABEL"),
            fontName=FONT,
            fontSize=FS_SMALL,
            fillColor=_hex(REPORT_COLORS["text_muted"]),
        ),
    )
    drawing.add(
        Rect(
            detection_legend_x,
            layout.legend_y - 2.6,
            10.0,
            4.2,
            fillColor=_hex(REPORT_COLORS["card_error_bg"]),
            strokeColor=_hex(REPORT_COLORS["danger"]),
            strokeWidth=0.45,
        ),
    )
    drawing.add(
        Circle(
            detection_legend_x + 5.0,
            layout.legend_y - 0.5,
            2.2,
            fillColor=_hex(REPORT_COLORS["danger"]),
            strokeColor=_hex(REPORT_COLORS["surface"]),
            strokeWidth=0.7,
        ),
    )
    drawing.add(
        String(
            detection_legend_x + 13.0,
            layout.legend_y - 2.6,
            tr("REPORT_TIMELINE_DETECTIONS_LABEL"),
            fontName=FONT,
            fontSize=FS_SMALL,
            fillColor=_hex(REPORT_COLORS["text_muted"]),
        ),
    )


def _draw_timeline_axes(
    drawing: Any,
    *,
    timeline_graph: TimelineGraphData,
    layout: _TimelineLayout,
) -> None:
    from reportlab.graphics.shapes import Line, Rect, String

    drawing.add(
        Rect(
            layout.plot_x,
            layout.plot_y,
            layout.plot_w,
            layout.plot_h,
            fillColor=_hex(REPORT_COLORS["surface"]),
            strokeColor=_hex(REPORT_COLORS["border"]),
            strokeWidth=0.8,
        ),
    )
    drawing.add(
        Rect(
            layout.plot_x,
            layout.plot_y,
            layout.plot_w,
            layout.detection_lane_h,
            fillColor=_hex(REPORT_COLORS["surface_alt"]),
            strokeColor=None,
            strokeWidth=0.0,
        ),
    )
    drawing.add(
        Line(
            layout.plot_x,
            layout.speed_plot_y - (layout.detection_lane_gap / 2.0),
            layout.plot_x + layout.plot_w,
            layout.speed_plot_y - (layout.detection_lane_gap / 2.0),
            strokeColor=_hex(REPORT_COLORS["table_row_border"]),
            strokeWidth=0.5,
        ),
    )

    mid_y = layout.speed_plot_y + (layout.speed_plot_h / 2.0)
    for y_value in (layout.speed_plot_y, mid_y, layout.speed_plot_y + layout.speed_plot_h):
        drawing.add(
            Line(
                layout.plot_x,
                y_value,
                layout.plot_x + layout.plot_w,
                y_value,
                strokeColor=_hex(REPORT_COLORS["table_row_border"]),
                strokeWidth=0.5,
            ),
        )

    drawing.add(
        String(
            layout.plot_x - 4.0,
            layout.speed_plot_y - 2.0,
            "0",
            fontName=FONT,
            fontSize=FS_SMALL,
            fillColor=_hex(REPORT_COLORS["text_muted"]),
            textAnchor="end",
        ),
    )
    drawing.add(
        String(
            layout.plot_x - 4.0,
            layout.speed_plot_y + layout.speed_plot_h - 2.0,
            str(int(round(timeline_graph.speed_ceiling_kmh))),
            fontName=FONT,
            fontSize=FS_SMALL,
            fillColor=_hex(REPORT_COLORS["text_muted"]),
            textAnchor="end",
        ),
    )
    drawing.add(
        String(
            layout.plot_x,
            layout.plot_y - 9.0,
            "0",
            fontName=FONT,
            fontSize=FS_SMALL,
            fillColor=_hex(REPORT_COLORS["text_muted"]),
        ),
    )
    drawing.add(
        String(
            layout.plot_x + layout.plot_w,
            layout.plot_y - 9.0,
            _format_time_label(timeline_graph.duration_s),
            fontName=FONT,
            fontSize=FS_SMALL,
            fillColor=_hex(REPORT_COLORS["text_muted"]),
            textAnchor="end",
        ),
    )


def _draw_timeline_intervals(
    drawing: Any,
    *,
    timeline_graph: TimelineGraphData,
    layout: _TimelineLayout,
) -> None:
    from reportlab.graphics.shapes import Circle, PolyLine, Rect

    speed_line_points: list[float] = []
    for interval in timeline_graph.intervals:
        x_start = _x_for_time(
            t_s=interval.start_t_s,
            plot_x=layout.plot_x,
            plot_w=layout.plot_w,
            duration_s=timeline_graph.duration_s,
        )
        x_end = _x_for_time(
            t_s=interval.end_t_s,
            plot_x=layout.plot_x,
            plot_w=layout.plot_w,
            duration_s=timeline_graph.duration_s,
        )
        interval_w = max(1.5, x_end - x_start)
        if interval.has_fault_evidence:
            detection_bar_y = layout.plot_y + 1.1
            detection_bar_h = max(3.4, layout.detection_lane_h - 2.2)
            drawing.add(
                Rect(
                    x_start,
                    detection_bar_y,
                    interval_w,
                    detection_bar_h,
                    fillColor=_hex(REPORT_COLORS["card_error_bg"]),
                    strokeColor=_hex(REPORT_COLORS["danger"]),
                    strokeWidth=0.45,
                ),
            )
            drawing.add(
                Circle(
                    x_start + (interval_w / 2.0),
                    detection_bar_y + (detection_bar_h / 2.0),
                    2.3,
                    fillColor=_hex(REPORT_COLORS["danger"]),
                    strokeColor=_hex(REPORT_COLORS["surface"]),
                    strokeWidth=0.75,
                ),
            )
        if interval.speed_min_kmh is not None or interval.speed_max_kmh is not None:
            band_low = interval.speed_min_kmh
            band_high = interval.speed_max_kmh
            if band_low is None:
                band_low = band_high
            if band_high is None:
                band_high = band_low
            assert band_low is not None
            assert band_high is not None
            y_low = _y_for_speed(
                speed_kmh=min(band_low, band_high),
                plot_y=layout.speed_plot_y,
                plot_h=layout.speed_plot_h,
                speed_ceiling_kmh=timeline_graph.speed_ceiling_kmh,
            )
            y_high = _y_for_speed(
                speed_kmh=max(band_low, band_high),
                plot_y=layout.speed_plot_y,
                plot_h=layout.speed_plot_h,
                speed_ceiling_kmh=timeline_graph.speed_ceiling_kmh,
            )
            drawing.add(
                Rect(
                    x_start,
                    y_low,
                    interval_w,
                    max(2.0, y_high - y_low),
                    fillColor=_hex(REPORT_COLORS["brand_surface"]),
                    strokeColor=_hex(REPORT_COLORS["brand_surface"]),
                    strokeWidth=0.0,
                ),
            )
        speed_value = _speed_value(interval)
        if speed_value is not None:
            y_speed = _y_for_speed(
                speed_kmh=speed_value,
                plot_y=layout.speed_plot_y,
                plot_h=layout.speed_plot_h,
                speed_ceiling_kmh=timeline_graph.speed_ceiling_kmh,
            )
            speed_line_points.extend([x_start, y_speed, x_end, y_speed])
    if speed_line_points:
        drawing.add(
            PolyLine(
                speed_line_points,
                strokeColor=_hex(REPORT_COLORS["brand"]),
                strokeWidth=1.8,
            ),
        )
