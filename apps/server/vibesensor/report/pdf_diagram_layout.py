"""Label placement and marker planning for the car location diagram."""

from __future__ import annotations

from .pdf_diagram_models import LabelRenderPlan, MarkerRenderPlan, MarkerState
from .theme import REPORT_COLORS


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
            (px - radius - 1.0, py - radius - 1.0, px + radius + 1.0, py + radius + 1.0)
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
