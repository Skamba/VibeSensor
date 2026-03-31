"""Drawing assembly for the car location diagram.

This module contains only ReportLab Canvas rendering code.  Pure layout
planning (marker placement, collision resolution, geometry math) lives
in ``diagram_layout``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from vibesensor.adapters.pdf.diagram_layout import (
    build_sensor_render_plan,
    extract_amp_by_location,
    highlight_map,
)
from vibesensor.adapters.pdf.diagram_layout import (
    location_points as _location_points,
)
from vibesensor.adapters.pdf.pdf_style import (
    BMW_LENGTH_MM as _BMW_LENGTH_MM,
)
from vibesensor.adapters.pdf.pdf_style import (
    BMW_WIDTH_MM as _BMW_WIDTH_MM,
)
from vibesensor.adapters.pdf.pdf_style import (
    REPORT_COLORS,
)
from vibesensor.shared.json_utils import as_float_or_none as _as_float

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from vibesensor.adapters.pdf.diagram_layout import LabelRenderPlan, MarkerRenderPlan
    from vibesensor.domain import LocationHotspotRow

__all__ = ["car_location_diagram"]


_DIAGRAM_HIGHLIGHT_COLORS = {
    "wheel/tire": REPORT_COLORS["brand"],
    "driveline": REPORT_COLORS["brand"],
    "engine": REPORT_COLORS["brand"],
    "unknown": REPORT_COLORS["brand"],
    "unknown_resonance": REPORT_COLORS["brand"],
}


def _build_sensor_render_plan(
    *,
    location_points: dict[str, tuple[float, float]],
    drawing_width: float,
    drawing_height: float,
    connected_locations: set[str],
    amp_by_location: dict[str, float],
    highlight: dict[str, str],
) -> tuple[list[MarkerRenderPlan], list[LabelRenderPlan], bool]:
    """Thin wrapper forwarding to ``diagram_layout.build_sensor_render_plan``."""
    return build_sensor_render_plan(
        location_points=location_points,
        drawing_width=drawing_width,
        drawing_height=drawing_height,
        connected_locations=connected_locations,
        amp_by_location=amp_by_location,
        highlight=highlight,
        colors=REPORT_COLORS,
    )


# ── Canvas drawing functions ─────────────────────────────────────────────────


def _draw_vehicle_shell(
    drawing: Any,
    *,
    x0: float,
    y0: float,
    car_w: float,
    car_h: float,
    color_surface: Any,
    color_border: Any,
    color_row_border: Any,
    color_text_primary: Any,
    hex_color: Any,
) -> None:
    from reportlab.graphics.shapes import Circle, Line, Rect, String

    center_x = x0 + (car_w / 2)
    drawing.add(
        Rect(
            x0,
            y0,
            car_w,
            car_h,
            rx=24,
            ry=24,
            fillColor=color_surface,
            strokeColor=color_border,
            strokeWidth=1.4,
        ),
    )
    drawing.add(
        Rect(
            x0 + (car_w * 0.08),
            y0 + (car_h * 0.10),
            car_w * 0.84,
            car_h * 0.80,
            rx=16,
            ry=16,
            fillColor=hex_color("#ffffff"),
            strokeColor=color_row_border,
            strokeWidth=0.7,
        ),
    )
    drawing.add(
        Line(
            center_x,
            y0 + 18,
            center_x,
            y0 + car_h - 18,
            strokeColor=color_row_border,
            strokeWidth=0.8,
        ),
    )
    front_axle_y = y0 + (car_h * 0.84)
    rear_axle_y = y0 + (car_h * 0.16)
    wheel_x_left = x0 + (car_w * 0.14)
    wheel_x_right = x0 + (car_w * 0.86)
    for axle_y in (front_axle_y, rear_axle_y):
        drawing.add(
            Line(
                wheel_x_left,
                axle_y,
                wheel_x_right,
                axle_y,
                strokeColor=color_row_border,
                strokeWidth=0.6,
            ),
        )
    wheel_fill = hex_color("#f8fbff")
    wheel_stroke = hex_color(REPORT_COLORS["axis"])
    for wx, wy in (
        (wheel_x_left, front_axle_y),
        (wheel_x_right, front_axle_y),
        (wheel_x_left, rear_axle_y),
        (wheel_x_right, rear_axle_y),
    ):
        drawing.add(
            Circle(wx, wy, 11, fillColor=wheel_fill, strokeColor=wheel_stroke, strokeWidth=1.0),
        )
    drawing.add(
        String(
            center_x - 16,
            y0 + car_h + 16,
            "DIAGRAM_LABEL_FRONT",
            fontName="Helvetica-Bold",
            fontSize=8,
            fillColor=color_text_primary,
        ),
    )
    drawing.add(
        String(
            center_x - 14,
            y0 - 16,
            "DIAGRAM_LABEL_REAR",
            fontName="Helvetica-Bold",
            fontSize=8,
            fillColor=color_text_primary,
        ),
    )


def _draw_markers_and_labels(
    drawing: Any, *, markers: list[Any], labels: list[Any], hex_color: Any
) -> None:
    from reportlab.graphics.shapes import Circle, String

    for marker in markers:
        drawing.add(
            Circle(
                marker.x,
                marker.y,
                marker.radius,
                fillColor=hex_color(marker.fill),
                strokeColor=hex_color(marker.stroke),
                strokeWidth=marker.stroke_width,
            ),
        )
    for label in labels:
        drawing.add(
            String(
                label.x,
                label.y,
                label.text,
                fontSize=label.font_size,
                textAnchor=label.anchor,
                fillColor=hex_color(label.color),
            ),
        )


# ── Public entry point ───────────────────────────────────────────────────────


def car_location_diagram(
    top_findings: Sequence[Mapping[str, object] | Any],
    summary: Mapping[str, object],
    location_rows: Sequence[LocationHotspotRow],
    *,
    content_width: float,
    tr: Callable[..., str],
    text_fn: Callable[..., str],
    diagram_width: float | None = None,
    diagram_height: float = 252,
) -> Any:
    """Build and return a ReportLab car location diagram Drawing."""
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib import colors

    hex_color = colors.HexColor
    drawing_w = diagram_width if diagram_width is not None else content_width * 0.44
    length_width_ratio = _BMW_LENGTH_MM / _BMW_WIDTH_MM
    drawing_h = max(220.0, float(diagram_height))
    drawing = Drawing(drawing_w, drawing_h)
    car_h = max(162.0, drawing_h - 88.0)
    car_w = car_h / length_width_ratio
    x0 = (drawing_w - car_w) / 2.0
    y0 = 54.0

    rendered_ratio = car_h / car_w if car_w > 0 else 0.0
    if abs(rendered_ratio - length_width_ratio) / length_width_ratio >= 0.02:
        raise ValueError(
            f"Car visual aspect ratio violated: rendered {rendered_ratio:.4f} vs source {length_width_ratio:.4f}",
        )

    color_surface = hex_color(REPORT_COLORS["surface"])
    color_border = hex_color(REPORT_COLORS["border"])
    color_row_border = hex_color(REPORT_COLORS["table_row_border"])
    color_text_primary = hex_color(REPORT_COLORS["text_primary"])

    _draw_vehicle_shell(
        drawing,
        x0=x0,
        y0=y0,
        car_w=car_w,
        car_h=car_h,
        color_surface=color_surface,
        color_border=color_border,
        color_row_border=color_row_border,
        color_text_primary=color_text_primary,
        hex_color=hex_color,
    )
    loc_points = _location_points(car_x=x0, car_y=y0, car_w=car_w, car_h=car_h)
    connected_locations, amp_by_location = extract_amp_by_location(
        summary,
        location_rows,
        as_float=_as_float,
    )
    highlight = highlight_map(top_findings, source_colors=_DIAGRAM_HIGHLIGHT_COLORS)
    markers, labels, _single_sensor = _build_sensor_render_plan(
        location_points=loc_points,
        drawing_width=drawing_w,
        drawing_height=drawing_h,
        connected_locations=connected_locations,
        amp_by_location=amp_by_location,
        highlight=highlight,
    )
    _draw_markers_and_labels(drawing, markers=markers, labels=labels, hex_color=hex_color)

    front_label = tr("DIAGRAM_LABEL_FRONT")
    rear_label = tr("DIAGRAM_LABEL_REAR")
    for item in drawing.contents:
        text = getattr(item, "text", None)
        if text == "DIAGRAM_LABEL_FRONT":
            item.text = front_label
        elif text == "DIAGRAM_LABEL_REAR":
            item.text = rear_label
    return drawing
