"""Focused diagram-visual regressions."""

from __future__ import annotations

from collections import Counter

from vibesensor.adapters.pdf.pdf_diagram_render import car_location_diagram


def test_car_diagram_shell_uses_contoured_paths_and_detail_polygons() -> None:
    diagram = car_location_diagram(
        [],
        {
            "sensor_locations": [],
            "sensor_intensity_by_location": [],
        },
        [],
        content_width=300.0,
        tr=lambda key, **kwargs: key,
        text_fn=lambda en, nl: en,
        diagram_width=200.0,
        diagram_height=252.0,
    )

    shape_counts = Counter(type(item).__name__ for item in diagram.contents)

    assert shape_counts["Path"] >= 4
    assert shape_counts["Polygon"] >= 4
    assert shape_counts["Rect"] >= 4
