"""PDF report car location diagram."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..report_analysis import _as_float
from ..report_theme import (
    HEAT_HIGH,
    HEAT_LOW,
    HEAT_MID,
    REPORT_COLORS,
)
from .pdf_helpers import _canonical_location, _source_color, color_blend

if TYPE_CHECKING:
    from collections.abc import Callable


def _amp_heat_color(norm: float) -> str:
    if norm <= 0.5:
        return color_blend(HEAT_LOW, HEAT_MID, norm * 2.0)
    return color_blend(HEAT_MID, HEAT_HIGH, (norm - 0.5) * 2.0)


def car_location_diagram(
    top_findings: list[dict[str, object]],
    summary: dict[str, object],
    location_rows: list[dict[str, object]],
    *,
    content_width: float,
    tr: Callable[..., str],
    text_fn: Callable[..., str],
    diagram_width: float | None = None,
    diagram_height: float = 252,
) -> Any:
    from reportlab.graphics.shapes import Circle, Drawing, Line, Rect, String
    from reportlab.lib import colors

    d_width = diagram_width if diagram_width is not None else content_width * 0.44
    bmw_length_mm = 5007.0
    bmw_width_mm = 1894.0
    length_width_ratio = bmw_length_mm / bmw_width_mm

    drawing_h = max(220.0, float(diagram_height))
    drawing = Drawing(d_width, drawing_h)
    car_h = max(162.0, drawing_h - 88.0)
    car_w = car_h / length_width_ratio
    x0 = (d_width - car_w) / 2.0
    y0 = 32.0
    cx = x0 + (car_w / 2)
    cy = y0 + (car_h / 2)

    # Outer body
    drawing.add(
        Rect(
            x0,
            y0,
            car_w,
            car_h,
            rx=24,
            ry=24,
            fillColor=colors.HexColor(REPORT_COLORS["surface"]),
            strokeColor=colors.HexColor(REPORT_COLORS["border"]),
            strokeWidth=1.4,
        )
    )
    # Cabin
    drawing.add(
        Rect(
            x0 + (car_w * 0.08),
            y0 + (car_h * 0.10),
            car_w * 0.84,
            car_h * 0.80,
            rx=16,
            ry=16,
            fillColor=colors.HexColor("#ffffff"),
            strokeColor=colors.HexColor(REPORT_COLORS["table_row_border"]),
            strokeWidth=0.7,
        )
    )
    # Center tunnel
    drawing.add(
        Line(
            cx,
            y0 + 18,
            cx,
            y0 + car_h - 18,
            strokeColor=colors.HexColor(REPORT_COLORS["table_row_border"]),
            strokeWidth=0.8,
        )
    )
    # Axles
    front_axle_y = y0 + (car_h * 0.84)
    rear_axle_y = y0 + (car_h * 0.16)
    drawing.add(
        Line(
            x0 + (car_w * 0.14),
            front_axle_y,
            x0 + (car_w * 0.86),
            front_axle_y,
            strokeColor=colors.HexColor(REPORT_COLORS["table_row_border"]),
            strokeWidth=0.6,
        )
    )
    drawing.add(
        Line(
            x0 + (car_w * 0.14),
            rear_axle_y,
            x0 + (car_w * 0.86),
            rear_axle_y,
            strokeColor=colors.HexColor(REPORT_COLORS["table_row_border"]),
            strokeWidth=0.6,
        )
    )
    # Wheel circles
    wheel_fill = colors.HexColor("#f8fbff")
    wheel_stroke = colors.HexColor(REPORT_COLORS["axis"])
    wheel_x_left = x0 + (car_w * 0.14)
    wheel_x_right = x0 + (car_w * 0.86)
    for wx, wy in [
        (wheel_x_left, front_axle_y),
        (wheel_x_right, front_axle_y),
        (wheel_x_left, rear_axle_y),
        (wheel_x_right, rear_axle_y),
    ]:
        drawing.add(
            Circle(wx, wy, 11, fillColor=wheel_fill, strokeColor=wheel_stroke, strokeWidth=1.0)
        )

    # Orientation labels
    drawing.add(
        String(
            cx - 16,
            y0 + car_h + 16,
            text_fn("FRONT", "VOOR"),
            fontName="Helvetica-Bold",
            fontSize=8,
            fillColor=colors.HexColor(REPORT_COLORS["text_primary"]),
        )
    )
    drawing.add(
        String(
            cx - 14,
            y0 - 16,
            text_fn("REAR", "ACHTER"),
            fontName="Helvetica-Bold",
            fontSize=8,
            fillColor=colors.HexColor(REPORT_COLORS["text_primary"]),
        )
    )

    # Vehicle coordinates
    location_points = {
        "front-left wheel": (wheel_x_left, front_axle_y),
        "front-right wheel": (wheel_x_right, front_axle_y),
        "rear-left wheel": (wheel_x_left, rear_axle_y),
        "rear-right wheel": (wheel_x_right, rear_axle_y),
        "engine bay": (cx, y0 + (car_h * 0.68)),
        "driveshaft tunnel": (cx, cy),
        "driver seat": (x0 + (car_w * 0.36), y0 + (car_h * 0.58)),
        "trunk": (cx, y0 + (car_h * 0.28)),
    }

    active_locations = {
        _canonical_location(loc) for loc in summary.get("sensor_locations", []) if str(loc).strip()
    }
    amp_by_location: dict[str, float] = {}
    sensor_intensity_rows = summary.get("sensor_intensity_by_location", [])
    if isinstance(sensor_intensity_rows, list):
        for row in sensor_intensity_rows:
            if not isinstance(row, dict):
                continue
            loc = _canonical_location(row.get("location"))
            p95_g = _as_float(row.get("p95_intensity_db")) or _as_float(
                row.get("mean_intensity_db")
            )
            if loc and p95_g is not None and p95_g > 0:
                amp_by_location[loc] = p95_g
    if not amp_by_location:
        for row in location_rows:
            if not isinstance(row, dict):
                continue
            loc = _canonical_location(row.get("location"))
            mean_g = _as_float(row.get("mean_g"))
            if loc and mean_g is not None and mean_g > 0:
                amp_by_location[loc] = mean_g
    min_amp = min(amp_by_location.values()) if amp_by_location else None
    max_amp = max(amp_by_location.values()) if amp_by_location else None

    highlight: dict[str, str] = {}
    for finding in top_findings[:3]:
        if not isinstance(finding, dict):
            continue
        loc = _canonical_location(finding.get("strongest_location"))
        if loc:
            highlight[loc] = _source_color(finding.get("source") or finding.get("suspected_source"))

    # Title
    drawing.add(
        String(
            4,
            drawing_h - 14,
            tr("EVIDENCE_AND_HOTSPOTS"),
            fontName="Helvetica-Bold",
            fontSize=9,
            fillColor=colors.HexColor(REPORT_COLORS["text_primary"]),
        )
    )

    single_sensor = len(amp_by_location) <= 1 and (min_amp is None or min_amp == max_amp)

    for name, (px, py) in location_points.items():
        is_active = name in active_locations or name in amp_by_location
        amp = amp_by_location.get(name)
        if single_sensor and is_active:
            fill = REPORT_COLORS["text_secondary"]
            radius = 5.4
        elif amp is not None and min_amp is not None and max_amp is not None:
            if max_amp > min_amp:
                norm = (amp - min_amp) / (max_amp - min_amp)
            else:
                norm = 1.0
            fill = _amp_heat_color(norm)
            radius = 5.0 + (norm * 2.2)
        elif is_active:
            fill = REPORT_COLORS["text_secondary"]
            radius = 5.4
        else:
            fill = "#d3dbe8"
            radius = 4.6

        drawing.add(
            Circle(
                px,
                py,
                radius,
                fillColor=colors.HexColor(fill),
                strokeColor=colors.HexColor(highlight.get(name, REPORT_COLORS["ink"])),
                strokeWidth=1.1 if name in highlight else 0.6,
            )
        )
        drawing.add(
            String(
                px + 10,
                py - 2,
                name,
                fontSize=6,
                fillColor=colors.HexColor(
                    REPORT_COLORS["ink"] if is_active else REPORT_COLORS["text_muted"]
                ),
            )
        )

    # Heat legend with numeric endpoints
    legend_y = 18
    legend_x = 8
    for i in range(0, 11):
        step = i / 10.0
        drawing.add(
            Rect(
                legend_x + (i * 8),
                legend_y,
                8,
                7,
                fillColor=colors.HexColor(_amp_heat_color(step)),
                strokeColor=colors.HexColor(_amp_heat_color(step)),
                strokeWidth=0.2,
            )
        )
    drawing.add(
        String(
            legend_x,
            legend_y - 10,
            tr("HEAT_LEGEND_LESS"),
            fontName="Helvetica",
            fontSize=6.5,
            fillColor=colors.HexColor(REPORT_COLORS["text_muted"]),
        )
    )
    drawing.add(
        String(
            legend_x + 82,
            legend_y - 10,
            tr("HEAT_LEGEND_MORE"),
            fontName="Helvetica",
            fontSize=6.5,
            fillColor=colors.HexColor(REPORT_COLORS["text_muted"]),
        )
    )
    if min_amp is not None and max_amp is not None:
        drawing.add(
            String(
                legend_x,
                legend_y + 10,
                f"{min_amp:.4f} g",
                fontName="Helvetica",
                fontSize=6,
                fillColor=colors.HexColor(REPORT_COLORS["text_muted"]),
            )
        )
        drawing.add(
            String(
                legend_x + 70,
                legend_y + 10,
                f"{max_amp:.4f} g",
                fontName="Helvetica",
                fontSize=6,
                fillColor=colors.HexColor(REPORT_COLORS["text_muted"]),
            )
        )
    if single_sensor:
        drawing.add(
            String(
                legend_x,
                legend_y - 20,
                tr("ONE_SENSOR_NOTE"),
                fontName="Helvetica",
                fontSize=6,
                fillColor=colors.HexColor(REPORT_COLORS["text_muted"]),
            )
        )
    return drawing
