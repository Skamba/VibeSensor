"""Drawing assembly for the car location diagram."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from vibesensor.domain import VibrationSource
from vibesensor.shared.utils.json_utils import as_float_or_none as _as_float
from vibesensor.adapters.pdf.pdf_style import (
    BMW_LENGTH_MM as _BMW_LENGTH_MM,
)
from vibesensor.adapters.pdf.pdf_style import (
    BMW_WIDTH_MM as _BMW_WIDTH_MM,
)
from vibesensor.adapters.pdf.pdf_style import (
    FINDING_SOURCE_COLORS,
    REPORT_COLORS,
)

if TYPE_CHECKING:
    from collections.abc import Callable

# ── Marker & label planning (merged from pdf_diagram_layout) ─────────────────

MarkerState = Literal["connected-active", "connected-inactive", "disconnected"]


@dataclass(frozen=True)
class MarkerRenderPlan:
    """Computed render parameters for a single location marker."""

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
    """Computed render parameters for a location label."""

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
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
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
    ordered_candidates = _LABEL_CANDIDATES_RIGHT if px < (width * 0.5) else _LABEL_CANDIDATES_LEFT
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
        marker = MarkerRenderPlan(
            name=name,
            x=px,
            y=py,
            state=state,
            fill=fill,
            stroke=fill,
            stroke_width=stroke_width,
            radius=radius,
        )
        markers.append(marker)
        occupied_boxes.append(
            (px - radius - 1.0, py - radius - 1.0, px + radius + 1.0, py + radius + 1.0),
        )

    marker_by_name = {marker.name: marker for marker in markers}
    labels: list[LabelRenderPlan] = []
    label_states = frozenset({"connected-active", "connected-inactive"})
    labeled_names = {
        marker.name
        for marker in markers
        if marker.state in label_states or marker.name in highlight
    }
    for name in sorted(
        labeled_names,
        key=lambda value: (location_points[value][1], location_points[value][0]),
    ):
        px, py = location_points[name]
        marker = marker_by_name.get(name)  # type: ignore[assignment]
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


# ── Location canonicalisation (merged from pdf_helpers) ───────────────────────

_FL_COMPACTS: frozenset[str] = frozenset({"frontleft", "frontleftwheel", "fl", "flwheel"})
_FR_COMPACTS: frozenset[str] = frozenset({"frontright", "frontrightwheel", "fr", "frwheel"})
_RL_COMPACTS: frozenset[str] = frozenset({"rearleft", "rearleftwheel", "rl", "rlwheel"})
_RR_COMPACTS: frozenset[str] = frozenset({"rearright", "rearrightwheel", "rr", "rrwheel"})


def _canonical_location(raw: object) -> str:
    token = str(raw or "").strip().lower().replace("_", "-")
    compact = "".join(ch for ch in token if ch.isalnum())
    if ("front" in token and "left" in token and "wheel" in token) or compact in _FL_COMPACTS:
        return "front-left wheel"
    if ("front" in token and "right" in token and "wheel" in token) or compact in _FR_COMPACTS:
        return "front-right wheel"
    if ("rear" in token and "left" in token and "wheel" in token) or compact in _RL_COMPACTS:
        return "rear-left wheel"
    if ("rear" in token and "right" in token and "wheel" in token) or compact in _RR_COMPACTS:
        return "rear-right wheel"
    if "trunk" in token:
        return "trunk"
    if "driveshaft" in token or "tunnel" in token:
        return "driveshaft tunnel"
    if "engine" in token:
        return "engine bay"
    if "driver" in token:
        return "driver seat"
    return token


def _source_color(source: object) -> str:
    src = str(source or "unknown").strip().lower()
    try:
        key = VibrationSource(src)
    except ValueError:
        key = VibrationSource.UNKNOWN
    return FINDING_SOURCE_COLORS.get(key, FINDING_SOURCE_COLORS[VibrationSource.UNKNOWN])


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
    raw_locations = summary.get("sensor_locations", [])
    connected_locations = {
        _canonical_location(loc)
        for loc in (raw_locations if isinstance(raw_locations, list) else [])
        if str(loc).strip()
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
            highlight[loc] = _source_color(finding.get("suspected_source"))
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
        (tr("SOURCE_WHEEL_TIRE"), FINDING_SOURCE_COLORS[VibrationSource.WHEEL_TIRE]),
        (tr("SOURCE_DRIVELINE"), FINDING_SOURCE_COLORS[VibrationSource.DRIVELINE]),
        (tr("SOURCE_ENGINE"), FINDING_SOURCE_COLORS[VibrationSource.ENGINE]),
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
