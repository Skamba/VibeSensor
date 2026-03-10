"""Drawing assembly for the car location diagram."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..domain_models import as_float_or_none as _as_float
from .pdf_diagram_layout import _build_sensor_render_plan, _estimate_text_width
from .pdf_helpers import _canonical_location, _source_color
from .theme import BMW_LENGTH_MM as _BMW_LENGTH_MM
from .theme import BMW_WIDTH_MM as _BMW_WIDTH_MM
from .theme import FINDING_SOURCE_COLORS, REPORT_COLORS

if TYPE_CHECKING:
    from collections.abc import Callable


def _location_points(
    *,
    car_x: float,
    car_y: float,
    car_w: float,
    car_h: float,
) -> dict[str, tuple[float, float]]:
    center_x = car_x + (car_w / 2)
    center_y = car_y + (car_h / 2)
    front_axle_y = car_y + (car_h * 0.84)
    rear_axle_y = car_y + (car_h * 0.16)
    wheel_x_left = car_x + (car_w * 0.14)
    wheel_x_right = car_x + (car_w * 0.86)
    return {
        "front-left wheel": (wheel_x_left, front_axle_y),
        "front-right wheel": (wheel_x_right, front_axle_y),
        "rear-left wheel": (wheel_x_left, rear_axle_y),
        "rear-right wheel": (wheel_x_right, rear_axle_y),
        "engine bay": (center_x, car_y + (car_h * 0.68)),
        "driveshaft tunnel": (center_x, center_y),
        "driver seat": (car_x + (car_w * 0.36), car_y + (car_h * 0.58)),
        "trunk": (center_x, car_y + (car_h * 0.28)),
    }


def _extract_amp_by_location(
    summary: dict[str, object],
    location_rows: list[dict[str, object]],
) -> tuple[set[str], dict[str, float]]:
    connected_locations = {
        _canonical_location(loc) for loc in summary.get("sensor_locations", []) if str(loc).strip()  # type: ignore[attr-defined]
    }
    amp_by_location: dict[str, float] = {}
    sensor_intensity_rows = summary.get("sensor_intensity_by_location", [])
    if isinstance(sensor_intensity_rows, list):
        for row in sensor_intensity_rows:
            if not isinstance(row, dict):
                continue
            loc = _canonical_location(row.get("location"))
            p95_val = _as_float(row.get("p95_intensity_db"))
            p95_db = p95_val if p95_val is not None else _as_float(row.get("mean_intensity_db"))
            if loc and p95_db is not None and p95_db > 0:
                amp_by_location[loc] = p95_db
    for row in location_rows:
        if not isinstance(row, dict):
            continue
        loc = _canonical_location(row.get("location"))
        mean_val = _as_float(row.get("mean_value"))
        if loc and loc not in amp_by_location and mean_val is not None and mean_val > 0:
            amp_by_location[loc] = mean_val
    connected_locations.update(amp_by_location.keys())
    return connected_locations, amp_by_location


def _highlight_map(top_findings: list[dict[str, object]]) -> dict[str, str]:
    highlight: dict[str, str] = {}
    for finding in top_findings[:3]:
        if not isinstance(finding, dict):
            continue
        loc = _canonical_location(finding.get("strongest_location"))
        if loc:
            highlight[loc] = _source_color(finding.get("source") or finding.get("suspected_source"))
    return highlight


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


def _draw_markers_and_labels(drawing: Any, *, markers: list[Any], labels: list[Any], hex_color: Any) -> None:  # type: ignore[no-untyped-def]
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


def _draw_source_legend(
    drawing: Any,
    *,
    diagram_width: float,
    single_sensor: bool,
    tr: Callable[..., str],
    color_text_primary: Any,
    hex_color: Any,
) -> None:
    from reportlab.graphics.shapes import Circle, String

    legend_items = [
        (tr("SOURCE_WHEEL_TIRE"), FINDING_SOURCE_COLORS["wheel/tire"]),
        (tr("SOURCE_DRIVELINE"), FINDING_SOURCE_COLORS["driveline"]),
        (tr("SOURCE_ENGINE"), FINDING_SOURCE_COLORS["engine"]),
    ]
    legend_x = 8.0
    title_y = 30.0
    swatch_y = title_y - 8
    drawing.add(
        String(
            legend_x,
            title_y,
            tr("SOURCE_LEGEND_TITLE"),
            fontName="Helvetica-Bold",
            fontSize=6,
            fillColor=color_text_primary,
        ),
    )
    if single_sensor:
        drawing.add(
            String(
                legend_x,
                title_y + 8.0,
                tr("ONE_SENSOR_NOTE"),
                fontName="Helvetica",
                fontSize=6,
                fillColor=hex_color(REPORT_COLORS["text_muted"]),
            ),
        )
    max_x = diagram_width - 8.0
    item_gap = 5.0
    row_gap = 9.0
    cursor_x = legend_x
    row = 0
    for label, color_hex in legend_items:
        item_w = 10.0 + _estimate_text_width(label, font_size=5.5) + item_gap
        if cursor_x > legend_x and (cursor_x + item_w) > max_x:
            row += 1
            cursor_x = legend_x
        lx = cursor_x
        ly = swatch_y - (row * row_gap)
        swatch_color = hex_color(color_hex)
        drawing.add(
            Circle(
                lx + 4, ly, 3, fillColor=swatch_color, strokeColor=swatch_color, strokeWidth=0.8
            ),
        )
        drawing.add(
            String(
                lx + 10,
                ly - 2,
                label,
                fontName="Helvetica",
                fontSize=5.5,
                fillColor=hex_color(REPORT_COLORS["text_secondary"]),
            ),
        )
        cursor_x += item_w


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
    location_points = _location_points(car_x=x0, car_y=y0, car_w=car_w, car_h=car_h)
    connected_locations, amp_by_location = _extract_amp_by_location(summary, location_rows)
    highlight = _highlight_map(top_findings)
    markers, labels, single_sensor = _build_sensor_render_plan(
        location_points=location_points,
        drawing_width=drawing_w,
        drawing_height=drawing_h,
        connected_locations=connected_locations,
        amp_by_location=amp_by_location,
        highlight=highlight,
    )
    _draw_markers_and_labels(drawing, markers=markers, labels=labels, hex_color=hex_color)
    _draw_source_legend(
        drawing,
        diagram_width=drawing_w,
        single_sensor=single_sensor,
        tr=tr,
        color_text_primary=color_text_primary,
        hex_color=hex_color,
    )

    front_label = tr("DIAGRAM_LABEL_FRONT")
    rear_label = tr("DIAGRAM_LABEL_REAR")
    for item in drawing.contents:
        text = getattr(item, "text", None)
        if text == "DIAGRAM_LABEL_FRONT":
            item.text = front_label
        elif text == "DIAGRAM_LABEL_REAR":
            item.text = rear_label
    return drawing
