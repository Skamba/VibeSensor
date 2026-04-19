"""Focused diagram-visual regressions and screenshot audit export."""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

import pytest
from test_support.findings import make_finding_payload
from test_support.report_helpers import minimal_summary

from vibesensor.adapters.pdf.pdf_diagram_render import car_location_diagram
from vibesensor.adapters.pdf.pdf_engine import build_report_pdf
from vibesensor.shared.boundaries.reporting import prepare_report_input
from vibesensor.use_cases.history.report_document import build_report_document

pdfium = pytest.importorskip("pypdfium2")


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


@pytest.mark.visual_audit
def test_appendix_b_diagram_visual_audit_exports_screenshot(tmp_path: Path) -> None:
    audit_root_env = os.getenv("VIBESENSOR_DIAGRAM_AUDIT_DIR")
    artifact_dir = Path(audit_root_env) if audit_root_env else tmp_path / "diagram_audit"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    finding = make_finding_payload(
        finding_id="F_DIAGRAM_AUDIT",
        suspected_source="wheel/tire",
        strongest_location="Front Left wheel",
        strongest_speed_band="60-80 km/h",
        confidence=0.82,
        frequency_hz_or_order="1x wheel order",
        signatures_observed=["1x wheel order"],
        matched_points=[
            {
                "speed_kmh": 62.0,
                "predicted_hz": 13.2,
                "matched_hz": 13.3,
                "location": "Front Left wheel",
                "amp": 0.10,
            },
            {
                "speed_kmh": 64.0,
                "predicted_hz": 13.6,
                "matched_hz": 13.7,
                "location": "Front Right wheel",
                "amp": 0.05,
            },
        ],
    )
    summary = minimal_summary(
        lang="en",
        sensor_count_used=4,
        sensor_locations=["Front Left", "Front Right", "Rear Left", "Rear Right"],
        sensor_locations_connected_throughout=[
            "Front Left",
            "Front Right",
            "Rear Left",
            "Rear Right",
        ],
        findings=[finding],
        top_causes=[finding],
    )

    pdf_bytes = build_report_pdf(build_report_document(prepare_report_input(summary)))
    pdf_path = artifact_dir / "diagram_visual_audit_report.pdf"
    pdf_path.write_bytes(pdf_bytes)

    document = pdfium.PdfDocument(str(pdf_path))
    page = document[1]
    bitmap = page.render(scale=2.5)
    image_path = artifact_dir / "diagram_visual_audit_page_2.png"
    bitmap.to_pil().save(image_path)

    audit_path = artifact_dir / "diagram_visual_audit.json"
    audit_path.write_text(
        json.dumps(
            {
                "scenario": "appendix_b_car_diagram_visual_audit",
                "pdf": str(pdf_path),
                "screenshots": [str(image_path)],
                "page_number": 2,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    assert image_path.is_file()
    assert audit_path.is_file()
