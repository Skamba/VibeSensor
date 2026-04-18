"""Unit tests for diagram_layout — pure geometry, no ReportLab dependency."""

from __future__ import annotations

import pytest

from vibesensor.adapters.pdf.diagram_layout import (
    bounds_overflow,
    boxes_overlap,
    build_sensor_render_plan,
    canonical_location,
    estimate_text_width,
    extract_amp_by_location,
    highlight_map,
    label_bbox,
    location_points,
    resolve_marker_states,
    source_color,
)
from vibesensor.domain import LocationHotspotRow, LocationIntensitySummary

# ── estimate_text_width ──────────────────────────────────────────────────────


def test_estimate_text_width_returns_minimum_for_short_text() -> None:
    assert estimate_text_width("", font_size=8.0) == 10.0


def test_estimate_text_width_scales_with_text_length() -> None:
    w1 = estimate_text_width("ab", font_size=8.0)
    w2 = estimate_text_width("abcd", font_size=8.0)
    assert w2 > w1


# ── label_bbox ───────────────────────────────────────────────────────────────


def test_label_bbox_start_anchor() -> None:
    bbox = label_bbox(x=10, y=20, text="test", anchor="start", font_size=8.0)
    assert bbox[0] == 10.0
    assert bbox[1] == 19.0  # y - 1.0


def test_label_bbox_end_anchor() -> None:
    bbox = label_bbox(x=100, y=20, text="test", anchor="end", font_size=8.0)
    width = estimate_text_width("test", font_size=8.0)
    assert bbox[0] == pytest.approx(100.0 - width)


def test_label_bbox_middle_anchor() -> None:
    bbox = label_bbox(x=100, y=20, text="test", anchor="middle", font_size=8.0)
    width = estimate_text_width("test", font_size=8.0)
    assert bbox[0] == pytest.approx(100.0 - width / 2.0)


# ── boxes_overlap ────────────────────────────────────────────────────────────


def test_boxes_overlap_detects_intersection() -> None:
    assert boxes_overlap((0, 0, 10, 10), (5, 5, 15, 15)) is True


def test_boxes_overlap_no_intersection() -> None:
    assert boxes_overlap((0, 0, 10, 10), (20, 20, 30, 30)) is False


def test_boxes_overlap_touching_edges_is_not_overlap() -> None:
    assert boxes_overlap((0, 0, 10, 10), (10, 0, 20, 10)) is False


# ── bounds_overflow ──────────────────────────────────────────────────────────


def test_bounds_overflow_no_overflow() -> None:
    assert bounds_overflow((10, 10, 90, 90), width=100, height=100) == 0.0


def test_bounds_overflow_left() -> None:
    assert bounds_overflow((-5, 10, 90, 90), width=100, height=100) > 0.0


def test_bounds_overflow_right() -> None:
    assert bounds_overflow((10, 10, 105, 90), width=100, height=100) > 0.0


# ── resolve_marker_states ────────────────────────────────────────────────────


def test_resolve_marker_states_classifies_correctly() -> None:
    states = resolve_marker_states(
        ["a", "b", "c"],
        connected_locations={"a", "b"},
        amp_by_location={"a": 10.0},
    )
    assert states["a"] == "connected-active"
    assert states["b"] == "connected-inactive"
    assert states["c"] == "disconnected"


# ── build_sensor_render_plan ─────────────────────────────────────────────────

_COLORS = {
    "brand": "#7c3aed",
    "axis": "#7b8da0",
    "text_secondary": "#52555e",
    "surface_alt": "#f1f2f6",
    "ink": "#1a1c24",
    "text_muted": "#6b6e78",
}


def test_build_sensor_render_plan_single_sensor() -> None:
    markers, labels, single = build_sensor_render_plan(
        location_points={"front-left wheel": (40.0, 180.0)},
        drawing_width=200,
        drawing_height=252,
        connected_locations={"front-left wheel"},
        amp_by_location={"front-left wheel": 20.0},
        highlight={"front-left wheel": "#ff0000"},
        colors=_COLORS,
    )
    assert single is True
    assert len(markers) == 1
    assert labels == []
    assert markers[0].fill == "#ff0000"
    assert markers[0].outer_radius > markers[0].mid_radius > markers[0].radius
    assert markers[0].outer_fill != markers[0].fill


def test_build_sensor_render_plan_multiple_sensors() -> None:
    pts = {
        "front-left wheel": (40.0, 180.0),
        "front-right wheel": (160.0, 180.0),
    }
    markers, labels, single = build_sensor_render_plan(
        location_points=pts,
        drawing_width=200,
        drawing_height=252,
        connected_locations=set(pts),
        amp_by_location={"front-left wheel": 20.0, "front-right wheel": 18.0},
        highlight={},
        colors=_COLORS,
    )
    assert single is False
    assert len(markers) == 2
    assert labels == []
    assert markers[0].fill != markers[1].fill
    assert markers[0].outer_radius > markers[0].mid_radius > markers[0].radius
    assert markers[1].outer_radius > markers[1].mid_radius > markers[1].radius


# ── canonical_location ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Front_Left_Wheel", "front-left wheel"),
        ("fl", "front-left wheel"),
        ("RearRight", "rear-right wheel"),
        ("rr", "rear-right wheel"),
        ("Trunk Area", "trunk"),
        ("driveshaft_tunnel", "driveshaft tunnel"),
        ("engine bay", "engine bay"),
        ("driver seat", "driver seat"),
        ("something else", "something else"),
    ],
)
def test_canonical_location(raw: str, expected: str) -> None:
    assert canonical_location(raw) == expected


# ── source_color ─────────────────────────────────────────────────────────────

_SOURCE_COLORS = {
    "wheel/tire": "#0f9d58",
    "driveline": "#7c3aed",
    "engine": "#c5221f",
    "unknown": "#52555e",
}


def test_source_color_known() -> None:
    assert source_color("wheel/tire", source_colors=_SOURCE_COLORS) == "#0f9d58"


def test_source_color_unknown_fallback() -> None:
    assert source_color("does-not-exist", source_colors=_SOURCE_COLORS) == "#52555e"


def test_source_color_none_fallback() -> None:
    assert source_color(None, source_colors=_SOURCE_COLORS) == "#52555e"


# ── location_points ──────────────────────────────────────────────────────────


def test_location_points_returns_all_locations() -> None:
    pts = location_points(car_x=0, car_y=0, car_w=100, car_h=200)
    expected_names = {
        "front-left wheel",
        "front-right wheel",
        "rear-left wheel",
        "rear-right wheel",
        "engine bay",
        "driveshaft tunnel",
        "driver seat",
        "trunk",
    }
    assert set(pts.keys()) == expected_names
    for x, y in pts.values():
        assert isinstance(x, float)
        assert isinstance(y, float)


# ── extract_amp_by_location ──────────────────────────────────────────────────


def test_extract_amp_by_location_from_intensity() -> None:
    summary: dict[str, object] = {
        "sensor_locations": ["front-left wheel"],
        "sensor_intensity_by_location": [
            LocationIntensitySummary(location="front-left wheel", p95_intensity_db=22.0),
        ],
    }
    connected, amp = extract_amp_by_location(summary, [])
    assert "front-left wheel" in connected
    assert amp["front-left wheel"] == 22.0


def test_extract_amp_by_location_from_rows() -> None:
    summary: dict[str, object] = {
        "sensor_locations": ["rear-right wheel"],
        "sensor_intensity_by_location": [],
    }
    rows = [
        LocationHotspotRow(location="rear-right wheel", mean_value=15.0),
    ]
    connected, amp = extract_amp_by_location(summary, rows)
    assert "rear-right wheel" in connected
    assert amp["rear-right wheel"] == 15.0


# ── highlight_map ────────────────────────────────────────────────────────────


def test_highlight_map_from_dicts() -> None:
    findings = [
        {"strongest_location": "front-left wheel", "suspected_source": "wheel/tire"},
    ]
    result = highlight_map(findings, source_colors=_SOURCE_COLORS)
    assert result == {"front-left wheel": "#0f9d58"}


def test_highlight_map_limits_to_three() -> None:
    findings = [{"strongest_location": f"loc{i}", "suspected_source": "unknown"} for i in range(5)]
    result = highlight_map(findings, source_colors=_SOURCE_COLORS)
    assert len(result) <= 3
