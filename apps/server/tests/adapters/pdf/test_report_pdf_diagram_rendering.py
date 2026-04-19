"""Rendered diagram and hotspot PDF tests."""

from __future__ import annotations

from vibesensor.adapters.pdf import pdf_diagram_render
from vibesensor.adapters.pdf.diagram_layout import estimate_text_width
from vibesensor.adapters.pdf.pdf_diagram_render import car_location_diagram
from vibesensor.domain import LocationIntensitySummary


def _rectangles_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def _text_item_box(item: object) -> tuple[float, float, float, float]:
    text = str(getattr(item, "text", ""))
    x = float(getattr(item, "x", 0.0))
    y = float(getattr(item, "y", 0.0))
    size = float(getattr(item, "fontSize", 5.5))
    anchor = str(getattr(item, "textAnchor", "start"))
    width = estimate_text_width(text, font_size=size)
    if anchor == "end":
        x0 = x - width
    elif anchor == "middle":
        x0 = x - (width / 2.0)
    else:
        x0 = x
    return (x0, y - 1.0, x0 + width, y + size + 1.0)


def _item_box(item: object) -> tuple[float, float, float, float] | None:
    if hasattr(item, "radius") and hasattr(item, "x") and hasattr(item, "y"):
        x = float(getattr(item, "x", 0.0))
        y = float(getattr(item, "y", 0.0))
        radius = float(getattr(item, "radius", 0.0))
        return (x - radius, y - radius, x + radius, y + radius)
    if hasattr(item, "x1") and hasattr(item, "y1") and hasattr(item, "x2") and hasattr(item, "y2"):
        x1 = float(getattr(item, "x1", 0.0))
        y1 = float(getattr(item, "y1", 0.0))
        x2 = float(getattr(item, "x2", 0.0))
        y2 = float(getattr(item, "y2", 0.0))
        return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
    if (
        hasattr(item, "width")
        and hasattr(item, "height")
        and hasattr(item, "x")
        and hasattr(item, "y")
    ):
        x = float(getattr(item, "x", 0.0))
        y = float(getattr(item, "y", 0.0))
        width = float(getattr(item, "width", 0.0))
        height = float(getattr(item, "height", 0.0))
        return (x, y, x + width, y + height)
    bounds_fn = getattr(item, "getBounds", None)
    if callable(bounds_fn):
        bounds = bounds_fn()
        if isinstance(bounds, tuple) and len(bounds) == 4:
            return tuple(float(value) for value in bounds)
    if hasattr(item, "text"):
        return _text_item_box(item)
    return None


def test_sparse_layout_omits_sensor_location_labels() -> None:
    summary = {
        "sensor_locations": ["front-left wheel", "rear-right wheel"],
        "sensor_intensity_by_location": [
            LocationIntensitySummary(location="front-left wheel", p95_intensity_db=22.0),
        ],
    }
    diagram = car_location_diagram(
        [{"strongest_location": "front-left wheel", "suspected_source": "wheel/tire"}],
        summary,
        [],
        content_width=300.0,
        tr=lambda key, **kwargs: key,
        text_fn=lambda en, nl: en,
        diagram_width=200.0,
        diagram_height=252.0,
    )

    sensor_labels = {
        str(item.text)
        for item in diagram.contents
        if hasattr(item, "text") and "wheel" in str(getattr(item, "text", ""))
    }
    assert sensor_labels == set()


def test_diagram_omits_source_legend_and_keeps_text_within_bounds() -> None:
    summary = {
        "sensor_locations": [
            "front-left wheel",
            "front-right wheel",
            "rear-left wheel",
            "rear-right wheel",
        ],
        "sensor_intensity_by_location": [
            LocationIntensitySummary(location="front-left wheel", p95_intensity_db=31.1),
            LocationIntensitySummary(location="front-right wheel", p95_intensity_db=34.9),
            LocationIntensitySummary(location="rear-left wheel", p95_intensity_db=30.9),
            LocationIntensitySummary(location="rear-right wheel", p95_intensity_db=31.4),
        ],
    }
    diagram = car_location_diagram(
        [{"strongest_location": "front-right wheel", "suspected_source": "wheel/tire"}],
        summary,
        [],
        content_width=300.0,
        tr=lambda key, **kwargs: key,
        text_fn=lambda en, nl: en,
        diagram_width=104.0,  # narrow width that previously triggered source-legend overlap
        diagram_height=252.0,
    )

    text_items = [item for item in diagram.contents if hasattr(item, "text")]

    db_labels = [item for item in text_items if str(getattr(item, "text", "")).endswith("dB")]
    assert not db_labels, "Map should not show raw intensity heat legend labels"

    source_labels = [
        item
        for item in text_items
        if str(getattr(item, "text", ""))
        in {
            "SOURCE_WHEEL_TIRE",
            "SOURCE_DRIVELINE",
            "SOURCE_ENGINE",
        }
    ]
    assert source_labels == []

    for item in text_items:
        box = _text_item_box(item)
        assert box[0] >= 0.0
        assert box[2] <= float(diagram.width) + 0.1
    assert all(
        str(getattr(item, "text", ""))
        not in {
            "front-left wheel",
            "front-right wheel",
            "rear-left wheel",
            "rear-right wheel",
            "engine bay",
            "driver seat",
            "driveshaft tunnel",
            "trunk",
        }
        for item in text_items
    )


def test_tall_narrow_page1_diagram_stays_inside_bounds_without_sensor_labels() -> None:
    summary = {
        "sensor_locations": [
            "front-left wheel",
            "front-right wheel",
            "rear-left wheel",
            "rear-right wheel",
        ],
        "sensor_intensity_by_location": [
            LocationIntensitySummary(location="front-left wheel", p95_intensity_db=31.1),
            LocationIntensitySummary(location="front-right wheel", p95_intensity_db=34.9),
            LocationIntensitySummary(location="rear-left wheel", p95_intensity_db=30.9),
            LocationIntensitySummary(location="rear-right wheel", p95_intensity_db=31.4),
        ],
    }
    diagram = car_location_diagram(
        [{"strongest_location": "front-right wheel", "suspected_source": "wheel/tire"}],
        summary,
        [],
        content_width=300.0,
        tr=lambda key, **kwargs: key,
        text_fn=lambda en, nl: en,
        diagram_width=128.0,
        diagram_height=490.0,
    )

    sensor_texts = [
        str(item.text)
        for item in diagram.contents
        if hasattr(item, "text")
        and str(getattr(item, "text", ""))
        in {
            "front-left wheel",
            "front-right wheel",
            "rear-left wheel",
            "rear-right wheel",
            "engine bay",
            "driver seat",
            "driveshaft tunnel",
            "trunk",
        }
    ]
    assert sensor_texts == []
    for item in diagram.contents:
        box = _item_box(item)
        if box is None:
            continue
        assert box[0] >= -0.1
        assert box[1] >= -0.1
        assert box[2] <= float(diagram.width) + 0.1
        assert box[3] <= float(diagram.height) + 0.1


def test_tall_narrow_page1_diagram_can_top_align_orientation_labels() -> None:
    summary = {
        "sensor_locations": [
            "front-left wheel",
            "front-right wheel",
            "rear-left wheel",
            "rear-right wheel",
        ],
        "sensor_intensity_by_location": [
            LocationIntensitySummary(location="front-left wheel", p95_intensity_db=31.1),
            LocationIntensitySummary(location="front-right wheel", p95_intensity_db=34.9),
            LocationIntensitySummary(location="rear-left wheel", p95_intensity_db=30.9),
            LocationIntensitySummary(location="rear-right wheel", p95_intensity_db=31.4),
        ],
    }
    centered = car_location_diagram(
        [{"strongest_location": "front-right wheel", "suspected_source": "wheel/tire"}],
        summary,
        [],
        content_width=300.0,
        tr=lambda key, **kwargs: key,
        text_fn=lambda en, nl: en,
        diagram_width=128.0,
        diagram_height=490.0,
    )
    top_aligned = car_location_diagram(
        [{"strongest_location": "front-right wheel", "suspected_source": "wheel/tire"}],
        summary,
        [],
        content_width=300.0,
        tr=lambda key, **kwargs: key,
        text_fn=lambda en, nl: en,
        diagram_width=128.0,
        diagram_height=490.0,
        vertical_align="top",
    )

    def label_y(diagram: object, text: str) -> float:
        for item in getattr(diagram, "contents", []):
            if hasattr(item, "text") and str(getattr(item, "text", "")) == text:
                return float(item.y)
        raise AssertionError(f"Label {text!r} not found")

    assert label_y(top_aligned, "DIAGRAM_LABEL_FRONT") > label_y(centered, "DIAGRAM_LABEL_FRONT")
    assert label_y(top_aligned, "DIAGRAM_LABEL_REAR") > label_y(centered, "DIAGRAM_LABEL_REAR")


def test_build_report_pdf_hotspot_panel_explains_intensity_and_certainty() -> None:
    from io import BytesIO

    from pypdf import PdfReader
    from test_support.report_helpers import minimal_summary

    from vibesensor.adapters.pdf.pdf_engine import build_report_pdf
    from vibesensor.shared.boundaries.reporting import prepare_report_input
    from vibesensor.use_cases.history.report_document import build_report_document

    summary = minimal_summary(
        lang="en",
        findings=[
            {
                "finding_id": "F001",
                "suspected_source": "wheel/tire",
                "confidence": 0.82,
                "strongest_location": "front-left wheel",
            }
        ],
        top_causes=[
            {
                "finding_id": "F001",
                "suspected_source": "wheel/tire",
                "confidence": 0.82,
                "strongest_location": "front-left wheel",
            }
        ],
        sensor_locations=["front-left wheel", "front-right wheel"],
        sensor_intensity_by_location=[
            LocationIntensitySummary(location="front-left wheel", p95_intensity_db=32.0),
            LocationIntensitySummary(location="front-right wheel", p95_intensity_db=18.0),
        ],
        samples=[],
    )

    pdf = build_report_pdf(build_report_document(prepare_report_input(summary)))
    text = " ".join((PdfReader(BytesIO(pdf)).pages[0].extract_text() or "").split()).lower()

    assert "why this corner wins" in text
    assert "dominant corner" in text
    assert "location confidence" in text


def test_pdf_diagram_render_module_no_longer_reexports_layout_helpers() -> None:
    removed_names = (
        "LabelRenderPlan",
        "MarkerRenderPlan",
        "MarkerState",
        "_estimate_text_width",
        "_choose_label_plan",
        "_resolve_marker_states",
        "_canonical_location",
    )
    for name in removed_names:
        assert not hasattr(pdf_diagram_render, name)
