"""Dense whole-run evidence rendering tests for PDF reports."""

from __future__ import annotations

from test_support.core import extract_pdf_text
from test_support.findings import make_finding_payload
from test_support.report_helpers import minimal_summary

from vibesensor.adapters.pdf.pdf_engine import build_report_pdf
from vibesensor.shared.boundaries.reporting import prepare_report_input
from vibesensor.use_cases.history.report_document import build_report_document


def _dense_summary(
    *,
    order_summary_overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    finding = make_finding_payload(
        finding_id="F_DENSE_WHEEL",
        finding_key="dense:episode-001",
        suspected_source="wheel/tire",
        confidence=0.78,
        strongest_location="Front Left",
        frequency_hz=12.6,
        order="1x wheel",
        amplitude_metric={
            "name": "vibration_strength_db",
            "value": 24.5,
            "units": "dB",
            "definition": {"_i18n_key": "METRIC"},
        },
    )
    order_summary: dict[str, object] = {
        "hypothesis_key": "wheel_front_1x",
        "suspected_source": "wheel/tire",
        "order_family": "wheel",
        "order_label": "1x wheel",
        "total_window_count": 10,
        "eligible_window_count": 8,
        "matched_window_count": 6,
        "support_ratio": 0.75,
        "reference_coverage_ratio": 0.875,
        "longest_contiguous_support_window_count": 4,
        "contiguous_support_ratio": 0.5,
        "support_intervals": [
            {
                "interval_index": 0,
                "start_window_index": 2,
                "end_window_index": 5,
                "matched_window_count": 4,
                "support_ratio": 1.0,
                "start_t_s": 20.0,
                "end_t_s": 32.0,
                "phase": "cruise",
                "speed_band": "60-80 km/h",
            }
        ],
        "phase_support": [],
        "harmonic_summaries": [],
        "stable_frequency_min_hz": 12.4,
        "stable_frequency_max_hz": 12.9,
        "exemplar_interval_index": 0,
        "dominant_phase": "cruise",
        "dominant_speed_band": "60-80 km/h",
        "strongest_location": "Front Left",
        "mean_relative_error": 0.03,
        "relative_error_stddev": 0.01,
        "drift_score": 0.1,
        "lock_score": 0.81,
        "peak_intensity_db": 24.5,
        "mean_vibration_strength_db": 18.2,
        "ref_sources": ["vehicle_speed"],
    }
    if order_summary_overrides:
        order_summary.update(order_summary_overrides)
    return minimal_summary(
        run_id="dense-report",
        lang="en",
        findings=[finding],
        top_causes=[finding],
        whole_run_order_summaries=[order_summary],
        analysis_metadata={
            "whole_run_artifacts_available": True,
            "whole_run_order_trace_summaries_available": True,
            "whole_run_order_trace_summary_count": 1,
        },
    )


def test_build_report_document_projects_dense_evidence_rows() -> None:
    document = build_report_document(prepare_report_input(_dense_summary()))

    assert len(document.appendix_c.dense_evidence_rows) == 1
    row = document.appendix_c.dense_evidence_rows[0]
    assert row.source_name == "Wheel / Tire"
    assert row.order_label == "1x wheel order"
    assert row.confidence_label == "High (78%)"
    assert row.support == "6/8 (75%)"
    assert row.support_ratio == 0.75
    assert row.reference_coverage_ratio == 0.875
    assert row.frequency_band == "12.4-12.9 Hz"
    assert row.peak_db == 24.5
    assert row.strongest_location == "Front Left"
    assert row.caveat == "Reference coverage 88%"


def test_build_report_pdf_renders_dense_evidence_chart_text() -> None:
    document = build_report_document(prepare_report_input(_dense_summary()))
    text = " ".join(extract_pdf_text(build_report_pdf(document)).split())

    assert "Dense evidence charts" in text
    assert "Support / reference coverage" in text
    assert "support 75% / reference 88%" in text
    assert "High (78%)" in text
    assert "6/8 (75%)" in text
    assert "12.4-12.9 Hz" in text
    assert "Reference coverage 88%" in text


def test_build_report_pdf_renders_missing_reference_caveat() -> None:
    summary = _dense_summary(
        order_summary_overrides={
            "reference_coverage_ratio": 0.0,
            "ref_sources": [],
        }
    )
    document = build_report_document(prepare_report_input(summary))
    text = " ".join(extract_pdf_text(build_report_pdf(document)).split())

    assert document.appendix_c.dense_evidence_rows[0].caveat == "Reference data unavailable"
    assert "Reference data unavailable" in text


def test_build_report_document_projects_dense_quality_caveat() -> None:
    summary = _dense_summary(
        order_summary_overrides={
            "reference_coverage_ratio": 1.0,
            "drift_score": 0.3,
        }
    )
    document = build_report_document(prepare_report_input(summary))

    assert document.appendix_c.dense_evidence_rows[0].caveat == ("Frequency drift across the run")


def test_build_report_document_projects_limited_window_quality_caveat() -> None:
    summary = _dense_summary(
        order_summary_overrides={
            "reference_coverage_ratio": 1.0,
            "mean_quality_score": 0.62,
            "limited_window_count": 3,
            "excluded_window_count": 2,
        }
    )
    document = build_report_document(prepare_report_input(summary))

    assert document.appendix_c.dense_evidence_rows[0].caveat == (
        "Usable window quality 62%; limited 3, excluded 2"
    )


def test_build_report_document_projects_shock_window_caveat() -> None:
    summary = _dense_summary(
        order_summary_overrides={
            "reference_coverage_ratio": 1.0,
            "mean_quality_score": 0.62,
            "limited_window_count": 3,
            "excluded_window_count": 2,
            "shock_transient_window_count": 2,
        }
    )
    document = build_report_document(prepare_report_input(summary))

    assert document.appendix_c.dense_evidence_rows[0].caveat == ("Road-shock windows filtered: 2")


def test_build_report_document_skips_dense_evidence_when_artifacts_are_unavailable() -> None:
    document = build_report_document(prepare_report_input(minimal_summary()))

    assert document.appendix_c.dense_evidence_rows == []
