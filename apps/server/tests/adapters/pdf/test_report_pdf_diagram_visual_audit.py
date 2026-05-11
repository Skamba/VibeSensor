"""Focused diagram-visual regressions."""

from __future__ import annotations

from vibesensor.adapters.pdf.pdf_diagram_render import car_location_diagram


def test_car_diagram_shell_renders_vehicle_context_without_primitive_pinning() -> None:
    diagram = car_location_diagram(
        [],
        {
            "sensor_locations": [],
            "sensor_intensity_by_location": [],
        },
        [],
        content_width=300.0,
        tr=lambda key, **kwargs: key,
        diagram_width=200.0,
        diagram_height=252.0,
    )

    item_types = {type(item).__name__ for item in diagram.contents}
    text_items = {str(item.text) for item in diagram.contents if hasattr(item, "text")}

    assert "Path" in item_types
    assert "Polygon" in item_types
    assert {"DIAGRAM_LABEL_FRONT", "DIAGRAM_LABEL_REAR"} <= text_items
