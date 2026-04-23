from __future__ import annotations

from test_support.findings import make_finding_payload
from test_support.report_helpers import minimal_summary

from vibesensor.shared.boundaries.reporting import prepare_persisted_report_input
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis


def _primary_finding() -> dict[str, object]:
    return make_finding_payload(
        finding_id="F_PRIMARY",
        suspected_source="wheel/tire",
        confidence=0.78,
        strongest_location="Front Left",
        strongest_speed_band="60-80 km/h",
        dominant_phase="cruise",
        matched_points=[
            {
                "t_s": 1.0,
                "speed_kmh": 64.0,
                "predicted_hz": 15.0,
                "matched_hz": 15.1,
                "location": "Front Left",
                "phase": "cruise",
                "amp": 0.11,
            },
            {
                "t_s": 1.5,
                "speed_kmh": 66.0,
                "predicted_hz": 15.1,
                "matched_hz": 15.2,
                "location": "Front Left",
                "phase": "cruise",
                "amp": 0.10,
            },
            {
                "t_s": 2.0,
                "speed_kmh": 68.0,
                "predicted_hz": 15.2,
                "matched_hz": 15.2,
                "location": "Rear Left",
                "phase": "cruise",
                "amp": 0.04,
            },
        ],
        evidence_metrics={
            "mean_relative_error": 0.03,
            "snr_db": 8.0,
            "matched_samples": 3,
        },
    )


def _alternative_finding() -> dict[str, object]:
    return make_finding_payload(
        finding_id="F_ALT",
        suspected_source="driveline",
        confidence=0.72,
        strongest_location="Rear Right",
        strongest_speed_band="60-80 km/h",
    )


def _prepared_report_input(
    *,
    analysis_metadata: dict[str, object],
    whole_run_context_intervals: list[dict[str, object]] | None = None,
    whole_run_diagnosis_summaries: list[dict[str, object]] | None = None,
    findings: list[dict[str, object]] | None = None,
    top_causes: list[dict[str, object]] | None = None,
) -> object:
    primary = _primary_finding()
    summary = minimal_summary(
        run_id="fallback-run",
        lang="en",
        metadata={
            "run_id": "fallback-run",
            "record_type": "metadata",
            "schema_version": "v2-jsonl",
            "feature_interval_s": 0.5,
        },
        sensor_count_used=2,
        sensor_locations=["Front Left", "Rear Left"],
        sensor_locations_connected_throughout=["Front Left", "Rear Left"],
        sensor_intensity_by_location=[
            {"location": "Front Left", "p95_intensity_db": 16.0, "peak_intensity_db": 18.5},
            {"location": "Rear Left", "p95_intensity_db": 9.0, "peak_intensity_db": 11.0},
        ],
        findings=findings if findings is not None else [primary, _alternative_finding()],
        top_causes=top_causes if top_causes is not None else [primary, _alternative_finding()],
        analysis_metadata=analysis_metadata,
    )
    if whole_run_context_intervals is not None:
        summary["whole_run_context_intervals"] = whole_run_context_intervals
    if whole_run_diagnosis_summaries is not None:
        summary["whole_run_diagnosis_summaries"] = whole_run_diagnosis_summaries
    return prepare_persisted_report_input(PersistedAnalysis.from_json_object(summary))


def test_prepare_persisted_report_input_builds_summary_only_fallback_diagnosis_summary() -> None:
    prepared = _prepared_report_input(
        analysis_metadata={
            "raw_backed_sample_count": 0,
            "raw_capture_mode": "summary_only",
        }
    )

    diagnosis = prepared.report_facts.whole_run_diagnosis_summaries

    assert len(diagnosis) == 1
    assert diagnosis[0].data_basis == "summary_only"
    assert diagnosis[0].uses_summary_fallback is True
    assert diagnosis[0].fallback_reason == "summary-only legacy confidence"
    assert {factor.factor_key for factor in diagnosis[0].counterevidence_factors} >= {
        "summary_only",
        "close_alternative",
    }


def test_prepare_persisted_report_input_builds_raw_backed_legacy_fallback_diagnosis_summary() -> (
    None
):
    prepared = _prepared_report_input(
        analysis_metadata={
            "raw_backed_sample_count": 48,
            "raw_capture_mode": "raw_backed",
        }
    )

    diagnosis = prepared.report_facts.whole_run_diagnosis_summaries

    assert len(diagnosis) == 1
    assert diagnosis[0].data_basis == "raw_backed"
    assert diagnosis[0].uses_summary_fallback is True
    assert (
        diagnosis[0].fallback_reason
        == "whole-run artifacts unavailable; replayed summary-era evidence"
    )
    assert diagnosis[0].location_proof_basis == "supporting_windows_raw_backed"
    assert "summary_only" not in {
        factor.factor_key for factor in diagnosis[0].counterevidence_factors
    }
    assert "legacy_context" in {
        factor.factor_key for factor in diagnosis[0].counterevidence_factors
    }


def test_prepare_persisted_report_input_marks_partial_whole_run_inputs_as_incomplete_fallback() -> (
    None
):
    prepared = _prepared_report_input(
        analysis_metadata={
            "raw_backed_sample_count": 48,
            "raw_capture_mode": "raw_backed",
            "whole_run_artifacts_available": True,
            "whole_run_context_available": True,
            "whole_run_context_window_count": 6,
            "whole_run_context_interval_count": 1,
            "whole_run_context_full_window_count": 6,
            "whole_run_context_partial_window_count": 0,
            "whole_run_context_missing_window_count": 0,
        },
        whole_run_context_intervals=[
            {
                "segment_index": 0,
                "phase": "cruise",
                "load_state": "light",
                "start_window_index": 0,
                "end_window_index": 5,
                "start_t_s": 0.0,
                "end_t_s": 3.0,
                "speed_min_kmh": 58.0,
                "speed_max_kmh": 68.0,
                "speed_band": "50-70",
                "full_context_window_count": 6,
                "partial_context_window_count": 0,
                "missing_context_window_count": 0,
            }
        ],
    )

    diagnosis = prepared.report_facts.whole_run_diagnosis_summaries

    assert len(diagnosis) == 1
    assert diagnosis[0].uses_summary_fallback is True
    assert (
        diagnosis[0].fallback_reason
        == "whole-run diagnosis inputs incomplete; replayed summary-era evidence"
    )
    assert diagnosis[0].exemplar_references[0].kind == "whole_run_context_interval"
    assert diagnosis[0].exemplar_references[0].context_segment_index == 0


def test_prepare_persisted_report_input_keeps_persisted_whole_run_diagnosis_summaries() -> None:
    prepared = _prepared_report_input(
        analysis_metadata={
            "raw_backed_sample_count": 48,
            "raw_capture_mode": "raw_backed",
            "whole_run_diagnosis_summaries_available": True,
            "whole_run_diagnosis_summary_count": 1,
        },
        whole_run_diagnosis_summaries=[
            {
                "diagnosis_key": "wheel_1x",
                "suspected_source": "wheel/tire",
                "rank": 1,
                "data_basis": "raw_backed",
                "support_score": 0.78,
                "counterevidence_score": 0.12,
                "total_score": 0.66,
                "location_proof_basis": "supporting_windows_raw_backed",
                "supporting_window_count": 6,
                "supporting_duration_s": 3.0,
                "supporting_sensor_count": 2,
                "dominant_location": "Front Left",
                "dominant_phase": "cruise",
                "dominant_speed_band": "60-80 km/h",
                "ambiguous_diagnosis": False,
                "ambiguous_location": False,
                "suspicious": False,
                "weak_spatial_separation": False,
                "has_reference_gap": False,
                "uses_summary_fallback": False,
                "support_factors": [],
                "counterevidence_factors": [],
                "exemplar_references": [],
            }
        ],
    )

    diagnosis = prepared.report_facts.whole_run_diagnosis_summaries

    assert len(diagnosis) == 1
    assert diagnosis[0].diagnosis_key == "wheel_1x"
    assert diagnosis[0].uses_summary_fallback is False
