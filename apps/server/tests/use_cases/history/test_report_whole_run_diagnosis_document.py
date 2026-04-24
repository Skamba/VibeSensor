from __future__ import annotations

from test_support.findings import make_finding_payload
from test_support.report_helpers import minimal_summary

from vibesensor.shared.boundaries.reporting import prepare_report_input
from vibesensor.use_cases.history.report_document import build_report_document


def test_build_report_document_prefers_persisted_whole_run_diagnosis_surfaces() -> None:
    wheel = make_finding_payload(
        finding_id="F_WHEEL",
        suspected_source="wheel/tire",
        confidence=0.81,
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
                "amp": 0.12,
            }
        ],
        evidence_metrics={
            "mean_relative_error": 0.03,
            "snr_db": 8.0,
            "matched_samples": 1,
        },
    )
    driveline = make_finding_payload(
        finding_id="F_DRIVELINE",
        suspected_source="driveline",
        confidence=0.72,
        strongest_location="Rear Right",
        strongest_speed_band="80-100 km/h",
        dominant_phase="accel",
    )
    summary = minimal_summary(
        run_id="whole-run-report",
        lang="en",
        metadata={
            "run_id": "whole-run-report",
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
        sensor_intensity_by_location=[
            {"location": "Front Left", "p95_intensity_db": 15.0, "peak_intensity_db": 18.0},
            {"location": "Front Right", "p95_intensity_db": 12.0, "peak_intensity_db": 15.0},
            {"location": "Rear Left", "p95_intensity_db": 14.0, "peak_intensity_db": 16.5},
            {"location": "Rear Right", "p95_intensity_db": 17.0, "peak_intensity_db": 20.0},
        ],
        findings=[wheel, driveline],
        top_causes=[wheel, driveline],
        analysis_metadata={
            "raw_backed_sample_count": 64,
            "raw_capture_mode": "raw_backed",
            "whole_run_diagnosis_summaries_available": True,
            "whole_run_diagnosis_summary_count": 2,
        },
        whole_run_diagnosis_summaries=[
            {
                "diagnosis_key": "driveline_1x",
                "suspected_source": "driveline",
                "rank": 1,
                "data_basis": "raw_backed",
                "support_score": 0.86,
                "counterevidence_score": 0.08,
                "total_score": 0.78,
                "location_proof_basis": "supporting_windows_raw_backed",
                "supporting_window_count": 12,
                "supporting_duration_s": 6.0,
                "supporting_sensor_count": 2,
                "stable_frequency_min_hz": 18.2,
                "stable_frequency_max_hz": 18.6,
                "dominant_location": "Rear Right",
                "runner_up_location": "Front Left",
                "dominant_phase": "accel",
                "dominant_speed_band": "80-100 km/h",
                "location_separation_db": 3.6,
                "dominance_ratio": 1.8,
                "alternative_source": "wheel/tire",
                "confidence_gap_to_alternative": 0.08,
                "ambiguous_diagnosis": False,
                "ambiguous_location": False,
                "suspicious": False,
                "weak_spatial_separation": False,
                "has_reference_gap": False,
                "uses_summary_fallback": False,
                "support_factors": [
                    {
                        "factor_key": "raw_backed",
                        "polarity": "support",
                        "severity": "high",
                        "weight": 0.10,
                        "details": {"raw_backed_sample_count": 64},
                    }
                ],
                "counterevidence_factors": [
                    {
                        "factor_key": "close_alternative",
                        "polarity": "counterevidence",
                        "severity": "low",
                        "weight": 0.08,
                        "details": {"alternative_source": "wheel/tire"},
                    }
                ],
                "exemplar_references": [],
            },
            {
                "diagnosis_key": "wheel_1x",
                "suspected_source": "wheel/tire",
                "rank": 2,
                "data_basis": "raw_backed",
                "support_score": 0.72,
                "counterevidence_score": 0.12,
                "total_score": 0.70,
                "location_proof_basis": "supporting_windows_raw_backed",
                "supporting_window_count": 9,
                "supporting_duration_s": 4.5,
                "supporting_sensor_count": 2,
                "stable_frequency_min_hz": 15.0,
                "stable_frequency_max_hz": 15.3,
                "dominant_location": "Front Left",
                "runner_up_location": "Rear Right",
                "dominant_phase": "cruise",
                "dominant_speed_band": "60-80 km/h",
                "location_separation_db": 2.4,
                "dominance_ratio": 1.4,
                "ambiguous_diagnosis": False,
                "ambiguous_location": False,
                "suspicious": False,
                "weak_spatial_separation": False,
                "has_reference_gap": False,
                "uses_summary_fallback": False,
                "support_factors": [],
                "counterevidence_factors": [],
                "exemplar_references": [],
            },
        ],
    )

    prepared = prepare_report_input(summary)
    document = build_report_document(prepared)

    assert document.verdict_page.suspected_source == "Driveline"
    assert document.verdict_page.inspect_first == "Rear-Right"
    assert document.verdict_page.also_consider == "Wheel / Tire"
    assert document.appendix_b.dominant_corner == "Rear-Right"
    assert document.appendix_b.runner_up_corner == "Front-Left"
    assert document.appendix_a.ranked_candidates[0].source_name == "Driveline"
    assert document.appendix_a.ranked_candidates[1].source_name == "Wheel / Tire"
    assert prepared.report_facts.confidence.signal_keys == ("raw_backed",)
    assert prepared.report_facts.confidence.caveat_keys == ("close_alternative",)
    assert any(
        "12" in row.value and "6.0" in row.value
        for row in document.verdict_page.proof_snapshot_rows
    )
    assert any(
        "18.2" in row.value and "18.6" in row.value
        for row in document.verdict_page.proof_snapshot_rows
    )


def test_build_report_document_uses_matching_persisted_source_when_top_row_is_ambiguous() -> None:
    wheel = make_finding_payload(
        finding_id="F_WHEEL",
        suspected_source="wheel/tire",
        confidence=0.81,
        strongest_location="Front Left",
        strongest_speed_band="100-110 km/h",
        dominant_phase="cruise",
    )
    driveline = make_finding_payload(
        finding_id="F_DRIVELINE",
        suspected_source="driveline",
        confidence=0.72,
        strongest_location="Front Left",
        strongest_speed_band="100-110 km/h",
        dominant_phase="cruise",
    )
    summary = minimal_summary(
        run_id="whole-run-ambiguous-report",
        lang="en",
        metadata={
            "run_id": "whole-run-ambiguous-report",
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
        findings=[wheel, driveline],
        top_causes=[wheel, driveline],
        analysis_metadata={
            "raw_backed_sample_count": 84,
            "raw_capture_mode": "raw_backed",
            "whole_run_diagnosis_summaries_available": True,
            "whole_run_diagnosis_summary_count": 3,
        },
        whole_run_diagnosis_summaries=[
            {
                "diagnosis_key": "driveshaft",
                "suspected_source": "driveline",
                "rank": 1,
                "data_basis": "raw_backed",
                "support_score": 0.36,
                "counterevidence_score": 0.16,
                "total_score": 0.80,
                "supporting_window_count": 22,
                "stable_frequency_min_hz": 39.8,
                "stable_frequency_max_hz": 39.8,
                "dominant_location": "Front Left",
                "dominant_phase": "cruise",
                "dominant_speed_band": "100-110 km/h",
                "alternative_source": "engine",
                "confidence_gap_to_alternative": 0.0,
                "ambiguous_diagnosis": True,
                "ambiguous_location": False,
                "suspicious": True,
                "weak_spatial_separation": False,
                "has_reference_gap": False,
                "uses_summary_fallback": False,
                "support_factors": [],
                "counterevidence_factors": [],
                "exemplar_references": [],
            },
            {
                "diagnosis_key": "engine",
                "suspected_source": "engine",
                "rank": 2,
                "data_basis": "raw_backed",
                "support_score": 0.36,
                "counterevidence_score": 0.16,
                "total_score": 0.80,
                "supporting_window_count": 22,
                "stable_frequency_min_hz": 51.2,
                "stable_frequency_max_hz": 51.2,
                "dominant_location": "Front Left",
                "dominant_phase": "cruise",
                "dominant_speed_band": "100-110 km/h",
                "alternative_source": "driveline",
                "confidence_gap_to_alternative": 0.0,
                "ambiguous_diagnosis": True,
                "ambiguous_location": False,
                "suspicious": True,
                "weak_spatial_separation": False,
                "has_reference_gap": False,
                "uses_summary_fallback": False,
                "support_factors": [],
                "counterevidence_factors": [],
                "exemplar_references": [],
            },
            {
                "diagnosis_key": "wheel",
                "suspected_source": "wheel/tire",
                "rank": 3,
                "data_basis": "raw_backed",
                "support_score": 0.36,
                "counterevidence_score": 0.16,
                "total_score": 0.80,
                "supporting_window_count": 22,
                "stable_frequency_min_hz": 12.9,
                "stable_frequency_max_hz": 12.9,
                "dominant_location": "Front Left",
                "dominant_phase": "cruise",
                "dominant_speed_band": "100-110 km/h",
                "alternative_source": "driveline",
                "confidence_gap_to_alternative": 0.0,
                "ambiguous_diagnosis": True,
                "ambiguous_location": False,
                "suspicious": True,
                "weak_spatial_separation": False,
                "has_reference_gap": False,
                "uses_summary_fallback": False,
                "support_factors": [
                    {
                        "factor_key": "raw_backed",
                        "polarity": "support",
                        "severity": "high",
                        "weight": 0.10,
                        "details": {"raw_backed_sample_count": 84},
                    }
                ],
                "counterevidence_factors": [
                    {
                        "factor_key": "rpm_context_gaps",
                        "polarity": "counterevidence",
                        "severity": "low",
                        "weight": 0.04,
                        "details": {"rpm_gap_window_count": 2},
                    }
                ],
                "exemplar_references": [],
            },
        ],
    )

    prepared = prepare_report_input(summary)
    document = build_report_document(prepared)

    assert document.verdict_page.suspected_source == "Wheel / Tire"
    assert document.verdict_page.inspect_first == "Front-Left"
    assert document.verdict_page.also_consider == "Driveline"
    assert document.appendix_a.ranked_candidates[0].source_name == "Wheel / Tire"
    assert document.appendix_a.ranked_candidates[1].source_name == "Driveline"
    assert prepared.report_facts.confidence.signal_keys == ("raw_backed",)
    assert prepared.report_facts.confidence.caveat_keys == ("rpm_context_gaps",)
    assert any(
        "12.9" in row.value
        for row in document.verdict_page.proof_snapshot_rows
        if row.label == "Stable frequency"
    )
