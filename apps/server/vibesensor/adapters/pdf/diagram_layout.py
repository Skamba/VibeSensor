"""Pure geometry and layout planning for the car location diagram.

All functions in this module are free of ReportLab dependencies and
can be unit-tested without importing any rendering library.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from vibesensor.domain import LocationHotspotRow

# ── Marker & label data types ────────────────────────────────────────────────

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


# ── Geometry primitives ──────────────────────────────────────────────────────


def estimate_text_width(text: str, *, font_size: float) -> float:
    """Approximate rendered width of *text* at *font_size*."""
    return max(10.0, float(len(text)) * font_size * 0.52)


def label_bbox(
    *,
    x: float,
    y: float,
    text: str,
    anchor: str,
    font_size: float,
) -> tuple[float, float, float, float]:
    """Return the bounding box ``(x0, y0, x1, y1)`` for a text label."""
    width = estimate_text_width(text, font_size=font_size)
    if anchor == "end":
        x0 = x - width
    elif anchor == "middle":
        x0 = x - (width / 2.0)
    else:
        x0 = x
    y0 = y - 1.0
    return (x0, y0, x0 + width, y0 + font_size + 2.0)


def boxes_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    """Return ``True`` when two axis-aligned bounding boxes overlap."""
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def bounds_overflow(
    box: tuple[float, float, float, float],
    *,
    width: float,
    height: float,
    margin: float = 2.0,
) -> float:
    """Total overflow of *box* outside the (0, 0, width, height) region."""
    left = max(0.0, margin - box[0])
    right = max(0.0, box[2] - (width - margin))
    bottom = max(0.0, margin - box[1])
    top = max(0.0, box[3] - (height - margin))
    return left + right + bottom + top


# ── Marker state resolution ─────────────────────────────────────────────────


def resolve_marker_states(
    location_names: list[str],
    *,
    connected_locations: set[str],
    amp_by_location: dict[str, float],
) -> dict[str, MarkerState]:
    """Classify each location as *connected-active*, *connected-inactive*, or *disconnected*."""
    states: dict[str, MarkerState] = {}
    for name in location_names:
        if name in amp_by_location:
            states[name] = "connected-active"
        elif name in connected_locations:
            states[name] = "connected-inactive"
        else:
            states[name] = "disconnected"
    return states


# ── Label collision resolution ───────────────────────────────────────────────

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


def choose_label_plan(
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
    """Choose the best label position for *name* at pixel (px, py).

    Tries several candidate offsets and picks the one with the lowest
    overlap + overflow penalty.
    """
    ordered_candidates = _LABEL_CANDIDATES_RIGHT if px < (width * 0.5) else _LABEL_CANDIDATES_LEFT
    best: tuple[float, LabelRenderPlan] | None = None
    for idx, (dx, dy, anchor) in enumerate(ordered_candidates):
        x = px + dx
        y = py + dy
        bbox = label_bbox(x=x, y=y, text=name, anchor=anchor, font_size=font_size)
        overlap_penalty = sum(1 for box in occupied_boxes if boxes_overlap(bbox, box))
        overflow_penalty = bounds_overflow(bbox, width=width, height=height)
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


# ── Full sensor render plan ─────────────────────────────────────────────────


def build_sensor_render_plan(
    *,
    location_points: dict[str, tuple[float, float]],
    drawing_width: float,
    drawing_height: float,
    connected_locations: set[str],
    amp_by_location: dict[str, float],
    highlight: dict[str, str],
    colors: dict[str, str],
) -> tuple[list[MarkerRenderPlan], list[LabelRenderPlan], bool]:
    """Plan marker and label positions for all sensor locations.

    *colors* must include at least the keys ``"text_secondary"``,
    ``"surface_alt"``, ``"ink"``, ``"text_muted"``.
    """
    states = resolve_marker_states(
        list(location_points),
        connected_locations=connected_locations,
        amp_by_location=amp_by_location,
    )
    min_amp = min(amp_by_location.values()) if amp_by_location else None
    max_amp = max(amp_by_location.values()) if amp_by_location else None
    active_count = sum(1 for value in states.values() if value == "connected-active")
    single_sensor = active_count == 1 and (min_amp is None or min_amp == max_amp)

    def active_radius(name: str, *, highlighted: bool) -> float:
        if min_amp is None or max_amp is None or min_amp == max_amp:
            return 6.2 if highlighted else 5.0
        amp = amp_by_location.get(name)
        if amp is None:
            return 6.2 if highlighted else 5.0
        normalized = (amp - min_amp) / (max_amp - min_amp)
        if highlighted:
            return 5.8 + (normalized * 0.6)
        return 4.4 + normalized

    markers: list[MarkerRenderPlan] = []
    occupied_boxes: list[tuple[float, float, float, float]] = []
    for name, (px, py) in location_points.items():
        state = states[name]
        if state == "connected-active":
            if name in highlight:
                fill = highlight[name]
                radius = active_radius(name, highlighted=True)
            else:
                fill = colors["text_secondary"]
                radius = active_radius(name, highlighted=False)
            stroke_width = 0.8
        elif state == "connected-inactive":
            fill = highlight.get(name, colors["surface_alt"])
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
        found_marker = marker_by_name.get(name)
        if found_marker is None:
            continue
        if found_marker.state == "connected-active":
            color = colors["ink"]
        elif found_marker.state == "connected-inactive":
            color = colors["text_secondary"]
        else:
            color = colors["text_muted"]
        label = choose_label_plan(
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


# ── Location canonicalization ────────────────────────────────────────────────

_FL_COMPACTS: frozenset[str] = frozenset({"frontleft", "frontleftwheel", "fl", "flwheel"})
_FR_COMPACTS: frozenset[str] = frozenset({"frontright", "frontrightwheel", "fr", "frwheel"})
_RL_COMPACTS: frozenset[str] = frozenset({"rearleft", "rearleftwheel", "rl", "rlwheel"})
_RR_COMPACTS: frozenset[str] = frozenset({"rearright", "rearrightwheel", "rr", "rrwheel"})


def canonical_location(raw: object) -> str:
    """Normalize a raw sensor location string to a canonical form."""
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


def source_color(source: object, *, source_colors: dict[str, str]) -> str:
    """Resolve a vibration source to its display color hex string.

    Uses a string-keyed *source_colors* mapping so no domain enum is needed.
    """
    src = str(source or "unknown").strip().lower()
    return source_colors.get(src, source_colors.get("unknown", "#52555e"))


def location_points(
    *,
    car_x: float,
    car_y: float,
    car_w: float,
    car_h: float,
) -> dict[str, tuple[float, float]]:
    """Compute (x, y) positions for each known sensor location on the car outline."""
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


def extract_amp_by_location(
    summary: Mapping[str, object],
    location_rows: Sequence[LocationHotspotRow],
    *,
    as_float: Callable[[object], float | None] | None = None,
) -> tuple[set[str], dict[str, float]]:
    """Extract per-location amplitude from summary and location rows.

    Returns ``(connected_locations, amp_by_location)``.

    *as_float* may be a ``(value) -> float | None`` coercion callable;
    when omitted a simple built-in coercion is used.
    """
    if as_float is None:

        def _coerce(v: object) -> float | None:
            if v is None:
                return None
            try:
                return float(v)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None

        coerce: Callable[[object], float | None] = _coerce
    else:
        coerce = as_float

    raw_locations = summary.get("sensor_locations", [])
    connected_locations = {
        canonical_location(loc)
        for loc in (raw_locations if isinstance(raw_locations, list) else [])
        if str(loc).strip()
    }
    amp_by_location: dict[str, float] = {}
    sensor_intensity_rows = summary.get("sensor_intensity_by_location", [])
    if isinstance(sensor_intensity_rows, list):
        for row in sensor_intensity_rows:
            loc = canonical_location(row.location)
            p95_db = row.p95_intensity_db or row.mean_intensity_db
            if loc and p95_db is not None and p95_db > 0:
                amp_by_location[loc] = p95_db
    for row in location_rows:
        loc = canonical_location(row.location)
        mean_val = coerce(row.mean_value)
        if loc and loc not in amp_by_location and mean_val is not None and mean_val > 0:
            amp_by_location[loc] = mean_val
    connected_locations.update(amp_by_location.keys())
    return connected_locations, amp_by_location


def highlight_map(
    top_findings: Sequence[Mapping[str, object]],
    *,
    source_colors: dict[str, str],
) -> dict[str, str]:
    """Build a location → color highlight mapping from the top findings.

    *top_findings* are expected to be ``Mapping`` objects (dicts or
    ``FindingPresentation``-like dataclasses accessed via attribute).
    """
    highlight: dict[str, str] = {}
    for finding in top_findings[:3]:
        if isinstance(finding, Mapping):
            loc = canonical_location(finding.get("strongest_location"))
            source = finding.get("suspected_source")
        else:
            loc = canonical_location(getattr(finding, "strongest_location", None))
            source = getattr(finding, "suspected_source", None)
        if loc:
            highlight[loc] = source_color(source, source_colors=source_colors)
    return highlight
