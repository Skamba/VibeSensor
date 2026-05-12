"""Rendered diagram-page regressions."""

from __future__ import annotations

from test_support.core import extract_pdf_text

from vibesensor.adapters.pdf.pdf_engine import build_report_pdf
from vibesensor.domain import LocationIntensitySummary
from vibesensor.shared.boundaries.reporting.document import (
    AppendixBData,
    ReportDocument,
)


def test_report_pdf_renders_sensor_topology_context_without_primitive_pinning() -> None:
    data = ReportDocument(
        title="Sensor topology review",
        run_id="sensor-topology-readable",
        sensor_count=4,
        sensor_locations=[
            "Front-Left",
            "Front-Right",
            "Rear-Left",
            "Rear-Right",
        ],
        sensor_intensity_by_location=[
            LocationIntensitySummary(
                location="Front-Left",
                sample_count=40,
                sample_coverage_ratio=1.0,
                p95_intensity_db=24.0,
            ),
            LocationIntensitySummary(
                location="Rear-Left",
                sample_count=40,
                sample_coverage_ratio=1.0,
                p95_intensity_db=12.0,
            ),
        ],
        appendix_b=AppendixBData(
            dominant_corner="Front-Left",
            runner_up_corner="Rear-Left",
            dominance_ratio_text="2.0x stronger",
            location_confidence="Strong",
            coverage_label="4 of 4 expected positions stayed connected.",
            coverage_notes=["Topology confirms the strongest sensor is on the front axle."],
        ),
    )

    text = " ".join(extract_pdf_text(build_report_pdf(data)).split())

    assert "Sensor Topology" in text
    assert "Front-Left" in text
    assert "Rear-Left" in text
    assert "2.0x stronger" in text
    assert "Topology confirms the strongest sensor is on the front axle." in text
