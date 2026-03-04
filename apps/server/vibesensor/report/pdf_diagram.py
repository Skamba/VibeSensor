"""PDF report car location diagram."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from ..runlog import as_float_or_none as _as_float
from .pdf_helpers import _canonical_location, _source_color
from .theme import (
    FINDING_SOURCE_COLORS,
    REPORT_COLORS,
)

if TYPE_CHECKING:
    from collections.abc import Callable


MarkerState = Literal["connected-active", "connected-inactive", "disconnected"]


@dataclass(frozen=True)
class MarkerRenderPlan:
    name: str
    x: float
    y: float
    state: MarkerState
    fill: str
    stroke: str
    stroke_width: float
    radius: float


@dataclass(frozen=True)
class LabelRenderPlan:
    name: str
    text: str
    x: float
    y: float
    anchor: str
    color: str
    font_size: float
    bbox: tuple[float, float, float, float]


def _estimate_text_width(text: str, *, font_size: float) -> float:
    return max(10.0, float(len(text)) * font_size * 0.52)


def _label_bbox(
    *,
    x: float,
    y: float,
    text: str,
    anchor: str,
    font_size: float,
) -> tuple[float, float, float, float]:
    width = _estimate_text_width(text, font_size=font_size)
    if anchor == "end":
        x0 = x - width
    elif anchor == "middle":
        x0 = x - (width / 2.0)
    else:
        x0 = x
    y0 = y - 1.0
    return (x0, y0, x0 + width, y0 + font_size + 2.0)


def _boxes_overlap(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def _bounds_overflow(
    box: tuple[float, float, float, float],
    *,
    width: float,
    height: float,
    margin: float = 2.0,
) -> float:
    left = max(0.0, margin - box[0])
    right = max(0.0, box[2] - (width - margin))
    bottom = max(0.0, margin - box[1])
    top = max(0.0, box[3] - (height - margin))
    return left + right + bottom + top


def _resolve_marker_states(
    location_names: list[str],
    *,
    connected_locations: set[str],
    amp_by_location: dict[str, float],
) -> dict[str, MarkerState]:
    states: dict[str, MarkerState] = {}
    for name in location_names:
        if name in amp_by_location:
            states[name] = "connected-active"
        elif name in connected_locations:
            states[name] = "connected-inactive"
        else:
            states[name] = "disconnected"
    return states


# Label placement candidate offsets (dx, dy, anchor), by preference order.
_LABEL_CANDIDATES_RIGHT: tuple[tuple[float, float, str], ...] = (
    (10.0, -2.0, "start"),
    (-10.0, -2.0, "end"),
    (0.0, 9.0, "middle"),
    (0.0, -11.0, "middle"),
)
_LABEL_CANDIDATES_LEFT: tuple[tuple[float, float, str], ...] = (
    (-10.0, -2.0, "end"),
    (10.0, -2.0, "start"),
    (0.0, 9.0, "middle"),
    (0.0, -11.0, "middle"),
)


def _choose_label_plan(
    *,
    name: str,
    px: float,
    py: float,
    width: float,
    height: float,
    occupied_boxes: list[tuple[float, float, float, float]],
    font_size: float,
    color: str,
) -> LabelRenderPlan:
    ordered_candidates = (
        _LABEL_CANDIDATES_RIGHT if px < (width * 0.5) else _LABEL_CANDIDATES_LEFT
    )

    best: tuple[float, LabelRenderPlan] | None = None
    for idx, (dx, dy, anchor) in enumerate(ordered_candidates):
        x = px + dx
        y = py + dy
        bbox = _label_bbox(x=x, y=y, text=name, anchor=anchor, font_size=font_size)
        overlap_penalty = sum(1 for box in occupied_boxes if _boxes_overlap(bbox, box))
        overflow_penalty = _bounds_overflow(bbox, width=width, height=height)
        score = (overlap_penalty * 1000.0) + (overflow_penalty * 10.0) + float(idx)
        candidate = LabelRenderPlan(
            name=name,
            text=name,
            x=x,
            y=y,
            anchor=anchor,
            color=color,
            font_size=font_size,
            bbox=bbox,
        )
        if best is None or score < best[0]:
            best = (score, candidate)

    if best is None:
        raise ValueError(f"No valid label placement found for {name!r} in diagram")
    return best[1]


def _build_sensor_render_plan(
    *,
    location_points: dict[str, tuple[float, float]],
    drawing_width: float,
    drawing_height: float,
    connected_locations: set[str],
    amp_by_location: dict[str, float],
    highlight: dict[str, str],
) -> tuple[list[MarkerRenderPlan], list[LabelRenderPlan], bool]:
    states = _resolve_marker_states(
        list(location_points),
        connected_locations=connected_locations,
        amp_by_location=amp_by_location,
    )

    min_amp = min(amp_by_location.values()) if amp_by_location else None
    max_amp = max(amp_by_location.values()) if amp_by_location else None
    active_count = sum(1 for value in states.values() if value == "connected-active")
    single_sensor = active_count == 1 and (min_amp is None or min_amp == max_amp)

    markers: list[MarkerRenderPlan] = []
    occupied_boxes: list[tuple[float, float, float, float]] = []
    for name, (px, py) in location_points.items():
        state = states[name]
        if state == "connected-active":
            if name in highlight:
                fill = highlight[name]
                radius = 6.2
            else:
                fill = REPORT_COLORS["text_secondary"]
                radius = 5.0
            stroke_width = 0.8
        elif state == "connected-inactive":
            fill = REPORT_COLORS["surface_alt"]
            radius = 4.8
            stroke_width = 0.8
        else:
            fill = "#e3e8f1"
            radius = 4.0
            stroke_width = 0.6
        stroke = fill

        marker = MarkerRenderPlan(
            name=name,
            x=px,
            y=py,
            state=state,
            fill=fill,
            stroke=stroke,
            stroke_width=stroke_width,
            radius=radius,
        )
        markers.append(marker)
        occupied_boxes.append(
            (px - radius - 1.0, py - radius - 1.0, px + radius + 1.0, py + radius + 1.0)
        )

    # Build a name -> marker dict for O(1) lookup in label loop.
    marker_by_name: dict[str, MarkerRenderPlan] = {m.name: m for m in markers}

    labels: list[LabelRenderPlan] = []
    _label_states = frozenset({"connected-active", "connected-inactive"})
    labeled_names = {
        m.name for m in markers if m.state in _label_states or m.name in highlight
    }
    for name in sorted(
        labeled_names, key=lambda value: (location_points[value][1], location_points[value][0])
    ):
        px, py = location_points[name]
        marker = marker_by_name.get(name)
        if marker is None:
            continue
        if marker.state == "connected-active":
            color = REPORT_COLORS["ink"]
        elif marker.state == "connected-inactive":
            color = REPORT_COLORS["text_secondary"]
        else:
            color = REPORT_COLORS["text_muted"]
        label = _choose_label_plan(
            name=name,
            px=px,
            py=py,
            width=drawing_width,
            height=drawing_height,
            occupied_boxes=occupied_boxes,
            font_size=6.0,
            color=color,
        )
        labels.append(label)
        occupied_boxes.append(label.bbox)

    return markers, labels, single_sensor


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

    # Local-bind HexColor to avoid repeated attribute lookup.
    _HexColor = colors.HexColor

    d_width = diagram_width if diagram_width is not None else content_width * 0.44
    bmw_length_mm = 5007.0
    bmw_width_mm = 1894.0
    length_width_ratio = bmw_length_mm / bmw_width_mm

    drawing_h = max(220.0, float(diagram_height))
    drawing = Drawing(d_width, drawing_h)
    car_h = max(162.0, drawing_h - 88.0)
    car_w = car_h / length_width_ratio
    x0 = (d_width - car_w) / 2.0
    y0 = 54.0

    # Aspect-ratio preservation check: the rendered car rectangle must
    # match the source BMW body ratio within 2 % tolerance.
    rendered_ratio = car_h / car_w if car_w > 0 else 0.0
    if abs(rendered_ratio - length_width_ratio) / length_width_ratio >= 0.02:
        raise ValueError(
            f"Car visual aspect ratio violated: rendered {rendered_ratio:.4f} "
            f"vs source {length_width_ratio:.4f}"
        )

    cx = x0 + (car_w / 2)
    cy = y0 + (car_h / 2)

    # Pre-resolve commonly used HexColor objects to avoid repeated construction.
    _color_surface = _HexColor(REPORT_COLORS["surface"])
    _color_border = _HexColor(REPORT_COLORS["border"])
    _color_row_border = _HexColor(REPORT_COLORS["table_row_border"])
    _color_text_primary = _HexColor(REPORT_COLORS["text_primary"])

    # Outer body
    drawing.add(
        Rect(
            x0,
            y0,
            car_w,
            car_h,
            rx=24,
            ry=24,
            fillColor=_color_surface,
            strokeColor=_color_border,
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
            fillColor=_HexColor("#ffffff"),
            strokeColor=_color_row_border,
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
            strokeColor=_color_row_border,
            strokeWidth=0.8,
        )
    )
    # Axles
    front_axle_y = y0 + (car_h * 0.84)
    rear_axle_y = y0 + (car_h * 0.16)
    wheel_x_left = x0 + (car_w * 0.14)
    wheel_x_right = x0 + (car_w * 0.86)
    # Axles
    for axle_y in (front_axle_y, rear_axle_y):
        drawing.add(
            Line(
                wheel_x_left,
                axle_y,
                wheel_x_right,
                axle_y,
                strokeColor=_color_row_border,
                strokeWidth=0.6,
            )
        )
    # Wheel circles
    wheel_fill = _HexColor("#f8fbff")
    wheel_stroke = _HexColor(REPORT_COLORS["axis"])
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
            tr("DIAGRAM_LABEL_FRONT"),
            fontName="Helvetica-Bold",
            fontSize=8,
            fillColor=_color_text_primary,
        )
    )
    drawing.add(
        String(
            cx - 14,
            y0 - 16,
            tr("DIAGRAM_LABEL_REAR"),
            fontName="Helvetica-Bold",
            fontSize=8,
            fillColor=_color_text_primary,
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

    connected_locations = {
        _canonical_location(loc) for loc in summary.get("sensor_locations", []) if str(loc).strip()
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
    # Also check location_rows for any locations not already covered
    # (sensor_intensity_by_location may only have partial data)
    for row in location_rows:
        if not isinstance(row, dict):
            continue
        loc = _canonical_location(row.get("location"))
        unit = str(row.get("unit") or "").strip().lower()
        mean_val = _as_float(row.get("mean_value"))
        if mean_val is None:
            mean_val = _as_float(row.get("mean_db")) if unit == "db" else None
        if loc and loc not in amp_by_location and mean_val is not None and mean_val > 0:
            amp_by_location[loc] = mean_val
    connected_locations.update(amp_by_location.keys())

    highlight: dict[str, str] = {}
    for finding in top_findings[:3]:
        if not isinstance(finding, dict):
            continue
        loc = _canonical_location(finding.get("strongest_location"))
        if loc:
            highlight[loc] = _source_color(finding.get("source") or finding.get("suspected_source"))

    marker_plan, label_plan, single_sensor = _build_sensor_render_plan(
        location_points=location_points,
        drawing_width=d_width,
        drawing_height=drawing_h,
        connected_locations=connected_locations,
        amp_by_location=amp_by_location,
        highlight=highlight,
    )
    for marker in marker_plan:
        drawing.add(
            Circle(
                marker.x,
                marker.y,
                marker.radius,
                fillColor=_HexColor(marker.fill),
                strokeColor=_HexColor(marker.stroke),
                strokeWidth=marker.stroke_width,
            )
        )

    for label in label_plan:
        drawing.add(
            String(
                label.x,
                label.y,
                label.text,
                fontSize=label.font_size,
                textAnchor=label.anchor,
                fillColor=_HexColor(label.color),
            )
        )

    # -- Source highlight legend (explains marker colors on the circles) --
    src_legend_items = [
        (tr("SOURCE_WHEEL_TIRE"), FINDING_SOURCE_COLORS["wheel/tire"]),
        (tr("SOURCE_DRIVELINE"), FINDING_SOURCE_COLORS["driveline"]),
        (tr("SOURCE_ENGINE"), FINDING_SOURCE_COLORS["engine"]),
    ]
    src_legend_x = 8.0
    # Keep source legend anchored low to avoid overlap with the car/rear label.
    src_title_y = 30.0
    src_swatch_y = src_title_y - 8
    drawing.add(
        String(
            src_legend_x,
            src_title_y,
            tr("SOURCE_LEGEND_TITLE"),
            fontName="Helvetica-Bold",
            fontSize=6,
            fillColor=_color_text_primary,
        )
    )
    if single_sensor:
        drawing.add(
            String(
                src_legend_x,
                src_title_y + 8.0,
                tr("ONE_SENSOR_NOTE"),
                fontName="Helvetica",
                fontSize=6,
                fillColor=_HexColor(REPORT_COLORS["text_muted"]),
            )
        )
    src_max_x = d_width - 8.0
    item_gap = 5.0
    row_gap = 9.0
    cursor_x = src_legend_x
    row = 0
    for label, color_hex in src_legend_items:
        item_w = 10.0 + _estimate_text_width(label, font_size=5.5) + item_gap
        if cursor_x > src_legend_x and (cursor_x + item_w) > src_max_x:
            row += 1
            cursor_x = src_legend_x
        lx = cursor_x
        ly = src_swatch_y - (row * row_gap)
        # Color swatch
        _swatch_color = _HexColor(color_hex)
        drawing.add(
            Circle(
                lx + 4,
                ly,
                3,
                fillColor=_swatch_color,
                strokeColor=_swatch_color,
                strokeWidth=0.8,
            )
        )
        drawing.add(
            String(
                lx + 10,
                ly - 2,
                label,
                fontName="Helvetica",
                fontSize=5.5,
                fillColor=_HexColor(REPORT_COLORS["text_secondary"]),
            )
        )
        cursor_x += item_w

    return drawing
