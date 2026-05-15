from __future__ import annotations

from test_support.findings import make_finding_payload
from test_support.pdf import extract_pdf_text
from test_support.report_helpers import minimal_summary

from vibesensor.adapters.pdf.pdf_engine import build_report_pdf
from vibesensor.shared.boundaries.reporting import prepare_persisted_report_input
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.use_cases.history.report_document import build_report_document


def test_pdf_renders_confidence_row_and_explicit_caveats() -> None:
    primary = make_finding_payload(
        finding_id="F_LOW",
        suspected_source="engine",
        confidence=0.74,
        strongest_location="Front Left",
        strongest_speed_band="60-80 km/h",
        weak_spatial_separation=True,
        matched_points=[
            {
                "t_s": 1.0,
                "speed_kmh": 64.0,
                "predicted_hz": 12.0,
                "matched_hz": 12.1,
                "location": "Front Left",
                "phase": "cruise",
                "amp": 0.08,
            },
            {
                "t_s": 1.5,
                "speed_kmh": 66.0,
                "predicted_hz": 15.0,
                "matched_hz": 15.6,
                "location": "Rear Right",
                "phase": "cruise",
                "amp": 0.08,
            },
        ],
        evidence_metrics={
            "mean_relative_error": 0.22,
            "snr_db": 2.5,
            "matched_samples": 2,
        },
    )
    alternative = make_finding_payload(
        finding_id="F_ALT",
        suspected_source="driveline",
        confidence=0.72,
        strongest_location="Rear Right",
        strongest_speed_band="60-80 km/h",
    )
    prepared = prepare_persisted_report_input(
        PersistedAnalysis.from_json_object(
            minimal_summary(
                run_id="confidence-render",
                lang="en",
                metadata={
                    "run_id": "confidence-render",
                    "record_type": "metadata",
                    "schema_version": "v2-jsonl",
                    "feature_interval_s": 0.5,
                },
                sensor_count_used=4,
                sensor_locations=["Front Left", "Front Right", "Rear Left", "Rear Right"],
                sensor_locations_connected_throughout=[
                    "Front Left",
                    "Front Right",
                    "Rear Left",
                    "Rear Right",
                ],
                findings=[primary, alternative],
                top_causes=[primary, alternative],
                analysis_metadata={
                    "raw_backed_sample_count": 0,
                    "raw_capture_mode": "summary_only",
                },
            )
        )
    )

    pdf = build_report_pdf(build_report_document(prepared))
    text = extract_pdf_text(pdf)

    assert "Confidence" in text
    assert "74%" in text
    assert "only summary-level evidence was available" in text
    assert "matched frequency drifted across 12.1-15.6 Hz" in text
