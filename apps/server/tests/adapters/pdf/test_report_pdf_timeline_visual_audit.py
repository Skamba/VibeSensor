"""Focused run-timeline visual regressions and screenshot audit export."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from test_support.findings import make_finding_payload
from test_support.report_helpers import minimal_summary

from vibesensor.adapters.pdf.pdf_engine import build_report_pdf
from vibesensor.shared.boundaries.reporting import prepare_report_input
from vibesensor.use_cases.history.report_document import build_report_document

pdfium = pytest.importorskip("pypdfium2")


@pytest.mark.visual_audit
def test_page_one_timeline_visual_audit_exports_screenshot(tmp_path: Path) -> None:
    audit_root_env = os.getenv("VIBESENSOR_TIMELINE_AUDIT_DIR")
    artifact_dir = Path(audit_root_env) if audit_root_env else tmp_path / "timeline_audit"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    finding = make_finding_payload(
        finding_id="F_TIMELINE_AUDIT",
        suspected_source="wheel/tire",
        strongest_location="Front Left wheel",
        strongest_speed_band="60-80 km/h",
        confidence=0.82,
        frequency_hz_or_order="1x wheel order",
        signatures_observed=["1x wheel order"],
    )
    summary = minimal_summary(
        lang="en",
        duration_s=18.0,
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
        phase_timeline=[
            {
                "phase": "cruise",
                "start_t_s": 0.0,
                "end_t_s": 6.0,
                "speed_min_kmh": 52.0,
                "speed_max_kmh": 60.0,
                "has_fault_evidence": False,
            },
            {
                "phase": "acceleration",
                "start_t_s": 6.0,
                "end_t_s": 11.0,
                "speed_min_kmh": 60.0,
                "speed_max_kmh": 74.0,
                "has_fault_evidence": True,
            },
            {
                "phase": "cruise",
                "start_t_s": 11.0,
                "end_t_s": 15.0,
                "speed_min_kmh": 70.0,
                "speed_max_kmh": 76.0,
                "has_fault_evidence": True,
            },
            {
                "phase": "deceleration",
                "start_t_s": 15.0,
                "end_t_s": 18.0,
                "speed_min_kmh": 58.0,
                "speed_max_kmh": 72.0,
                "has_fault_evidence": False,
            },
        ],
    )

    pdf_bytes = build_report_pdf(build_report_document(prepare_report_input(summary)))
    pdf_path = artifact_dir / "timeline_visual_audit_report.pdf"
    pdf_path.write_bytes(pdf_bytes)

    document = pdfium.PdfDocument(str(pdf_path))
    page = document[0]
    bitmap = page.render(scale=2.5)
    image_path = artifact_dir / "timeline_visual_audit_page_1.png"
    bitmap.to_pil().save(image_path)

    audit_path = artifact_dir / "timeline_visual_audit.json"
    audit_path.write_text(
        json.dumps(
            {
                "scenario": "page_one_timeline_visual_audit",
                "pdf": str(pdf_path),
                "screenshots": [str(image_path)],
                "page_number": 1,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    assert image_path.is_file()
    assert audit_path.is_file()
