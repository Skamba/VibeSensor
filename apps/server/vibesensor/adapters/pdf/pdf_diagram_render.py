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

    from vibesensor.domain import LocationHotspotRow

__all__ = ["car_location_diagram"]


_DIAGRAM_HIGHLIGHT_COLORS = {
    "wheel/tire": REPORT_COLORS["brand"],
    "driveline": REPORT_COLORS["brand"],
    "engine": REPORT_COLORS["brand"],
    "unknown": REPORT_COLORS["brand"],
    "unknown_resonance": REPORT_COLORS["brand"],
}


def _fit_vehicle_shell_rect(
    *,
    drawing_width: float,
    drawing_height: float,
    vertical_align: str = "center",
) -> tuple[float, float, float, float]:
    vehicle_ratio = _BMW_WIDTH_MM / _BMW_LENGTH_MM
    horizontal_pad = max(10.0, drawing_width * 0.085)
    orientation_reserve = 16.0
    top_bottom_pad = 8.0
    box_w = max(44.0, drawing_width - (2.0 * horizontal_pad))
    box_h = max(92.0, drawing_height - (2.0 * orientation_reserve) - top_bottom_pad)
    box_ratio = box_w / box_h if box_h > 0 else vehicle_ratio
    if box_ratio > vehicle_ratio:
        car_h = box_h
        car_w = car_h * vehicle_ratio
    else:
        car_w = box_w
        car_h = car_w / vehicle_ratio
    x0 = (drawing_width - car_w) / 2.0
    spare_h = max(0.0, box_h - car_h)
    if vertical_align == "top":
        y0 = orientation_reserve + spare_h
    elif vertical_align == "center":
        y0 = orientation_reserve + (spare_h / 2.0)
    else:
        raise ValueError("vertical_align must be 'center' or 'top'")
    return (x0, y0, car_w, car_h)


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
    from reportlab.graphics.shapes import Circle, Line, Path, Polygon, Rect, String

    center_x = x0 + (car_w / 2)
    tire_w = max(10.0, car_w * 0.11)
    tire_h = max(20.0, car_h * 0.12)

    def px(ratio: float) -> float:
        return x0 + (car_w * ratio)

    def py(ratio: float) -> float:
        return y0 + (car_h * ratio)

    body = Path(
        fillColor=color_surface,
        strokeColor=color_border,
        strokeWidth=1.55,
    )
    body.moveTo(center_x, py(0.985))
    body.curveTo(px(0.24), py(0.972), px(0.12), py(0.89), px(0.10), py(0.78))
    body.curveTo(px(0.08), py(0.68), px(0.09), py(0.56), px(0.11), py(0.48))
    body.curveTo(px(0.13), py(0.37), px(0.08), py(0.21), px(0.12), py(0.11))
    body.curveTo(px(0.17), py(0.04), px(0.29), py(0.01), center_x, py(0.015))
    body.curveTo(px(0.71), py(0.01), px(0.83), py(0.04), px(0.88), py(0.11))
    body.curveTo(px(0.92), py(0.21), px(0.87), py(0.37), px(0.89), py(0.48))
    body.curveTo(px(0.91), py(0.56), px(0.92), py(0.68), px(0.90), py(0.78))
    body.curveTo(px(0.88), py(0.89), px(0.76), py(0.972), center_x, py(0.985))
    body.closePath()
    drawing.add(body)

    roof_shell = Path(
        fillColor=hex_color("#ffffff"),
        strokeColor=color_row_border,
        strokeWidth=1.0,
    )
    roof_shell.moveTo(center_x, py(0.79))
    roof_shell.curveTo(px(0.35), py(0.785), px(0.25), py(0.70), px(0.23), py(0.58))
    roof_shell.lineTo(px(0.23), py(0.34))
    roof_shell.curveTo(px(0.25), py(0.24), px(0.35), py(0.18), center_x, py(0.17))
    roof_shell.curveTo(px(0.65), py(0.18), px(0.75), py(0.24), px(0.77), py(0.34))
    roof_shell.lineTo(px(0.77), py(0.58))
    roof_shell.curveTo(px(0.75), py(0.70), px(0.65), py(0.785), center_x, py(0.79))
    roof_shell.closePath()
    drawing.add(roof_shell)

    windshield = Polygon(
        [
            px(0.34),
            py(0.73),
            px(0.66),
            py(0.73),
            px(0.72),
            py(0.60),
            px(0.28),
            py(0.60),
        ],
        fillColor=hex_color("#f6f9ff"),
        strokeColor=color_row_border,
        strokeWidth=0.75,
    )
    rear_window = Polygon(
        [
            px(0.31),
            py(0.31),
            px(0.69),
            py(0.31),
            px(0.62),
            py(0.20),
            px(0.38),
            py(0.20),
        ],
        fillColor=hex_color("#f6f9ff"),
        strokeColor=color_row_border,
        strokeWidth=0.75,
    )
    drawing.add(windshield)
    drawing.add(rear_window)

    hood_seam = Path(strokeColor=color_row_border, strokeWidth=0.82)
    hood_seam.moveTo(px(0.27), py(0.83))
    hood_seam.curveTo(px(0.37), py(0.79), px(0.63), py(0.79), px(0.73), py(0.83))
    drawing.add(hood_seam)

    hatch_seam = Path(strokeColor=color_row_border, strokeWidth=0.82)
    hatch_seam.moveTo(px(0.30), py(0.15))
    hatch_seam.curveTo(px(0.40), py(0.18), px(0.60), py(0.18), px(0.70), py(0.15))
    drawing.add(hatch_seam)

    door_left_x = px(0.37)
    door_right_x = px(0.63)
    belt_low_y = py(0.42)
    belt_high_y = py(0.56)
    drawing.add(
        Line(
            door_left_x,
            belt_low_y,
            door_left_x,
            belt_high_y,
            strokeColor=color_row_border,
            strokeWidth=0.72,
        ),
    )
    drawing.add(
        Line(
            door_right_x,
            belt_low_y,
            door_right_x,
            belt_high_y,
            strokeColor=color_row_border,
            strokeWidth=0.72,
        ),
    )
    drawing.add(
        Line(
            center_x,
            py(0.18),
            center_x,
            py(0.79),
            strokeColor=color_row_border,
            strokeWidth=0.92,
        ),
    )
    drawing.add(
        Line(
            px(0.29),
            py(0.47),
            px(0.71),
            py(0.47),
            strokeColor=color_row_border,
            strokeWidth=0.62,
        ),
    )

    mirror_fill = hex_color("#ffffff")
    mirror_left = Polygon(
        [
            px(0.15),
            py(0.70),
            px(0.07),
            py(0.67),
            px(0.12),
            py(0.63),
        ],
        fillColor=mirror_fill,
        strokeColor=color_row_border,
        strokeWidth=0.8,
    )
    mirror_right = Polygon(
        [
            px(0.85),
            py(0.70),
            px(0.93),
            py(0.67),
            px(0.88),
            py(0.63),
        ],
        fillColor=mirror_fill,
        strokeColor=color_row_border,
        strokeWidth=0.8,
    )
    drawing.add(mirror_left)
    drawing.add(mirror_right)

    lamp_fill = hex_color("#fff7d9")
    tail_fill = hex_color("#ffe3e6")
    for lx, ly, fill in (
        (px(0.24), py(0.90), lamp_fill),
        (px(0.76), py(0.90), lamp_fill),
        (px(0.24), py(0.08), tail_fill),
        (px(0.76), py(0.08), tail_fill),
    ):
        drawing.add(
            Circle(
                lx,
                ly,
                max(2.2, car_w * 0.022),
                fillColor=fill,
                strokeColor=color_row_border,
                strokeWidth=0.58,
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
                strokeWidth=0.7,
            ),
        )
    wheel_fill = hex_color("#f7f9fd")
    wheel_stroke = hex_color(REPORT_COLORS["axis"])
    for wx, wy in (
        (wheel_x_left, front_axle_y),
        (wheel_x_right, front_axle_y),
        (wheel_x_left, rear_axle_y),
        (wheel_x_right, rear_axle_y),
    ):
        drawing.add(
            Rect(
                wx - (tire_w / 2.0),
                wy - (tire_h / 2.0),
                tire_w,
                tire_h,
                rx=max(2.5, tire_w * 0.25),
                ry=max(2.5, tire_h * 0.25),
                fillColor=wheel_fill,
                strokeColor=wheel_stroke,
                strokeWidth=1.0,
            ),
        )
    drawing.add(
        String(
            center_x,
            y0 + car_h + 10.5,
            "DIAGRAM_LABEL_FRONT",
            fontName="Helvetica-Bold",
            fontSize=7.5,
            fillColor=color_text_primary,
            textAnchor="middle",
        ),
    )
    drawing.add(
        String(
            center_x,
            y0 - 11.5,
            "DIAGRAM_LABEL_REAR",
            fontName="Helvetica-Bold",
            fontSize=7.5,
            fillColor=color_text_primary,
            textAnchor="middle",
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
                marker.outer_radius,
                fillColor=hex_color(marker.outer_fill),
                strokeColor=hex_color(marker.outer_fill),
                strokeWidth=0.0,
            ),
        )
        drawing.add(
            Circle(
                marker.x,
                marker.y,
                marker.mid_radius,
                fillColor=hex_color(marker.mid_fill),
                strokeColor=hex_color(marker.mid_fill),
                strokeWidth=0.0,
            ),
        )
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
    diagram_width: float | None = None,
    diagram_height: float = 252,
    vertical_align: str = "center",
) -> Any:
    """Build and return a ReportLab car location diagram Drawing."""
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib import colors

    hex_color = colors.HexColor
    drawing_w = diagram_width if diagram_width is not None else content_width * 0.44
    length_width_ratio = _BMW_LENGTH_MM / _BMW_WIDTH_MM
    drawing_h = max(220.0, float(diagram_height))
    drawing = Drawing(drawing_w, drawing_h)
    x0, y0, car_w, car_h = _fit_vehicle_shell_rect(
        drawing_width=drawing_w,
        drawing_height=drawing_h,
        vertical_align=vertical_align,
    )

    rendered_ratio = car_h / car_w if car_w > 0 else 0.0
    if abs(rendered_ratio - length_width_ratio) / length_width_ratio >= 0.02:
        raise ValueError(
            f"Car visual aspect ratio violated: rendered {rendered_ratio:.4f} vs source {length_width_ratio:.4f}",
        )

    color_surface = hex_color(REPORT_COLORS["surface_alt"])
    color_border = hex_color(REPORT_COLORS["axis"])
    color_row_border = hex_color(REPORT_COLORS["border"])
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
    markers, labels, _single_sensor = build_sensor_render_plan(
        location_points=loc_points,
        drawing_width=drawing_w,
        drawing_height=drawing_h,
        connected_locations=connected_locations,
        amp_by_location=amp_by_location,
        highlight=highlight,
        colors=REPORT_COLORS,
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
