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
    mid_fill: str
    mid_radius: float
    outer_fill: str
    outer_radius: float


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


def _clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    token = value.strip().lstrip("#")
    if len(token) != 6:
        raise ValueError(f"Expected a 6-digit hex color, got {value!r}")
    return (int(token[0:2], 16), int(token[2:4], 16), int(token[4:6], 16))


def _blend_hex(base: str, target: str, *, target_weight: float) -> str:
    weight = _clamp_unit(target_weight)
    base_rgb = _hex_to_rgb(base)
    target_rgb = _hex_to_rgb(target)
    mixed = tuple(
        round((base_rgb[idx] * (1.0 - weight)) + (target_rgb[idx] * weight)) for idx in range(3)
    )
    return f"#{mixed[0]:02x}{mixed[1]:02x}{mixed[2]:02x}"


def _intensity_fill(*, normalized: float, colors: Mapping[str, str]) -> str:
    low = colors.get("surface_alt", "#f1f2f6")
    high = colors.get("axis", "#7b8da0")
    return _blend_hex(low, high, target_weight=_clamp_unit(normalized))


def _gradient_layers(
    *,
    base_fill: str,
    core_radius: float,
    emphasis: float,
    state: MarkerState,
) -> tuple[str, float, str, float]:
    normalized = _clamp_unit(emphasis)
    if state == "connected-active":
        mid_fill = _blend_hex(base_fill, "#ffffff", target_weight=0.34 - (normalized * 0.10))
        outer_fill = _blend_hex(base_fill, "#ffffff", target_weight=0.56 - (normalized * 0.18))
        mid_radius = core_radius + 0.85 + (normalized * 0.15)
        outer_radius = mid_radius + 1.05 + (normalized * 0.20)
    elif state == "connected-inactive":
        mid_fill = _blend_hex(base_fill, "#ffffff", target_weight=0.32)
        outer_fill = _blend_hex(base_fill, "#ffffff", target_weight=0.50)
        mid_radius = core_radius + 0.45
        outer_radius = mid_radius + 0.65
    else:
        mid_fill = _blend_hex(base_fill, "#ffffff", target_weight=0.20)
        outer_fill = _blend_hex(base_fill, "#ffffff", target_weight=0.34)
        mid_radius = core_radius + 0.25
        outer_radius = mid_radius + 0.35
    return (mid_fill, mid_radius, outer_fill, outer_radius)


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
    highlight_fill: bool = False,
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

    def intensity_emphasis(name: str) -> float:
        if name not in amp_by_location:
            return 0.45
        if min_amp is None or max_amp is None or min_amp == max_amp:
            return 1.0
        amp = amp_by_location[name]
        return _clamp_unit((amp - min_amp) / (max_amp - min_amp))

    def intensity_fill_weight(name: str) -> float:
        if name not in amp_by_location:
            return 0.45
        if min_amp is None or max_amp is None:
            return 0.72
        if min_amp == max_amp:
            return 1.0 if active_count == 1 else 0.72
        amp = amp_by_location[name]
        return _clamp_unit((amp - min_amp) / (max_amp - min_amp))

    def active_radius(name: str, *, highlighted: bool) -> float:
        normalized = intensity_emphasis(name)
        if highlighted:
            return 4.25 + (normalized * 0.35)
        return 4.0 + (normalized * 0.55)

    markers: list[MarkerRenderPlan] = []
    for name, (px, py) in location_points.items():
        state = states[name]
        if state == "connected-active":
            if single_sensor and name in highlight:
                fill = highlight[name]
                stroke = fill
                radius = active_radius(name, highlighted=True)
                stroke_width = 0.75
            else:
                fill = _intensity_fill(
                    normalized=intensity_fill_weight(name),
                    colors=colors,
                )
                if highlight_fill and name in highlight:
                    fill = highlight[name]
                stroke = highlight.get(name, fill)
                radius = active_radius(name, highlighted=name in highlight)
                stroke_width = 0.9 if name in highlight else 0.75
        elif state == "connected-inactive":
            if name in highlight:
                fill = highlight[name]
                stroke = highlight[name]
                radius = 3.6
                stroke_width = 0.62
            else:
                fill = colors["surface_alt"]
                stroke = fill
                radius = 3.15
                stroke_width = 0.58
        else:
            fill = "#d8dfea"
            stroke = fill
            radius = 2.6
            stroke_width = 0.5
        emphasis = intensity_emphasis(name) if state == "connected-active" else 0.45
        mid_fill, mid_radius, outer_fill, outer_radius = _gradient_layers(
            base_fill=fill,
            core_radius=radius,
            emphasis=emphasis,
            state=state,
        )
        marker = MarkerRenderPlan(
            name=name,
            x=px,
            y=py,
            state=state,
            fill=fill,
            stroke=stroke,
            stroke_width=stroke_width,
            radius=radius,
            mid_fill=mid_fill,
            mid_radius=mid_radius,
            outer_fill=outer_fill,
            outer_radius=outer_radius,
        )
        markers.append(marker)
    return markers, [], single_sensor


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
