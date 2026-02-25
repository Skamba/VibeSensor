from __future__ import annotations

from vibesensor.report.pdf_diagram import (
    _amp_heat_color,
    _build_sensor_render_plan,
    _resolve_marker_states,
    car_location_diagram,
)
from vibesensor.report.theme import HEAT_HIGH, HEAT_LOW, REPORT_COLORS


def _rectangles_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def test_sensor_state_mapping_connected_active_inactive_and_disconnected() -> None:
    states = _resolve_marker_states(
        ["front-left wheel", "front-right wheel", "engine bay"],
        connected_locations={"front-left wheel", "front-right wheel"},
        amp_by_location={"front-left wheel": 21.0},
    )

    assert states["front-left wheel"] == "connected-active"
    assert states["front-right wheel"] == "connected-inactive"
    assert states["engine bay"] == "disconnected"


def test_marker_colors_follow_heat_scale_and_disconnected_is_neutral() -> None:
    location_points = {
        "front-left wheel": (40.0, 180.0),
        "front-right wheel": (160.0, 180.0),
        "engine bay": (100.0, 140.0),
    }
    markers, _, _ = _build_sensor_render_plan(
        location_points=location_points,
        drawing_width=220.0,
        drawing_height=252.0,
        connected_locations={"front-left wheel", "front-right wheel"},
        amp_by_location={"front-left wheel": 10.0, "front-right wheel": 30.0},
        highlight={},
    )
    marker_by_name = {marker.name: marker for marker in markers}

    assert marker_by_name["front-left wheel"].fill == HEAT_LOW
    assert marker_by_name["front-right wheel"].fill == HEAT_HIGH
    assert marker_by_name["front-left wheel"].fill != REPORT_COLORS["text_secondary"]
    assert marker_by_name["front-right wheel"].fill != REPORT_COLORS["text_secondary"]
    assert marker_by_name["engine bay"].state == "disconnected"
    assert marker_by_name["engine bay"].fill != HEAT_LOW
    assert marker_by_name["engine bay"].fill != HEAT_HIGH


def test_label_placement_stays_in_bounds_and_avoids_overlap_for_dense_layout() -> None:
    location_points = {
        "front-left wheel": (36.0, 198.0),
        "front-right wheel": (164.0, 198.0),
        "rear-left wheel": (36.0, 76.0),
        "rear-right wheel": (164.0, 76.0),
        "engine bay": (100.0, 160.0),
        "driveshaft tunnel": (100.0, 130.0),
        "driver seat": (78.0, 145.0),
        "trunk": (100.0, 102.0),
    }
    markers, labels, _ = _build_sensor_render_plan(
        location_points=location_points,
        drawing_width=200.0,
        drawing_height=252.0,
        connected_locations=set(location_points.keys()),
        amp_by_location={name: 10.0 + idx for idx, name in enumerate(location_points.keys())},
        highlight={"front-left wheel": REPORT_COLORS["success"]},
    )

    marker_boxes = {
        marker.name: (
            marker.x - marker.radius - 1.0,
            marker.y - marker.radius - 1.0,
            marker.x + marker.radius + 1.0,
            marker.y + marker.radius + 1.0,
        )
        for marker in markers
    }

    assert len(labels) == len(location_points)
    for label in labels:
        assert label.bbox[0] >= 0.0
        assert label.bbox[1] >= 0.0
        assert label.bbox[2] <= 200.0
        assert label.bbox[3] <= 252.0
        for marker_name, marker_box in marker_boxes.items():
            if marker_name != label.name:
                assert not _rectangles_overlap(label.bbox, marker_box)

    for idx in range(len(labels)):
        for jdx in range(idx + 1, len(labels)):
            assert not _rectangles_overlap(labels[idx].bbox, labels[jdx].bbox)


def test_sparse_layout_renders_only_connected_sensor_labels() -> None:
    summary = {
        "sensor_locations": ["front-left wheel", "rear-right wheel"],
        "sensor_intensity_by_location": [
            {"location": "front-left wheel", "p95_intensity_db": 22.0},
        ],
    }
    diagram = car_location_diagram(
        [{"strongest_location": "front-left wheel", "source": "wheel/tire"}],
        summary,
        [],
        content_width=300.0,
        tr=lambda key, **kwargs: key,
        text_fn=lambda en, nl: en,
        diagram_width=200.0,
        diagram_height=252.0,
    )

    labels = {
        str(item.text)
        for item in diagram.contents
        if hasattr(item, "text") and "wheel" in str(getattr(item, "text", ""))
    }
    assert labels == {"front-left wheel", "rear-right wheel"}


def test_single_sensor_uses_heat_midpoint_not_neutral_grey() -> None:
    location_points = {"front-left wheel": (40.0, 180.0)}
    markers, _, single_sensor = _build_sensor_render_plan(
        location_points=location_points,
        drawing_width=220.0,
        drawing_height=252.0,
        connected_locations={"front-left wheel"},
        amp_by_location={"front-left wheel": 25.0},
        highlight={},
    )

    assert single_sensor is True
    assert markers[0].fill == _amp_heat_color(0.5)
    assert markers[0].fill != REPORT_COLORS["text_secondary"]
