from __future__ import annotations

from test_support.findings import make_finding_payload
from test_support.report_helpers import minimal_summary

from vibesensor.shared.boundaries.reporting import prepare_persisted_report_input
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.use_cases.history.report_document import build_report_document


def test_prepare_persisted_report_input_builds_high_confidence_from_raw_backed_signals() -> None:
    primary = make_finding_payload(
        finding_id="F_CONFIDENT",
        suspected_source="wheel/tire",
        confidence=0.78,
        strongest_location="Front Left",
        strongest_speed_band="60-80 km/h",
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
                "location": "Front Left",
                "phase": "cruise",
                "amp": 0.10,
            },
            {
                "t_s": 2.5,
                "speed_kmh": 70.0,
                "predicted_hz": 15.3,
                "matched_hz": 15.3,
                "location": "Front Left",
                "phase": "cruise",
                "amp": 0.09,
            },
        ],
        evidence_metrics={
            "mean_relative_error": 0.03,
            "snr_db": 8.0,
            "matched_samples": 4,
        },
    )
    prepared = prepare_persisted_report_input(
        PersistedAnalysis.from_json_object(
            minimal_summary(
                run_id="confidence-high",
                lang="en",
                metadata={
                    "run_id": "confidence-high",
                    "record_type": "metadata",
                    "schema_version": "v2-jsonl",
                    "feature_interval_s": 0.5,
                },
                sensor_count_used=2,
                sensor_locations=["Front Left", "Rear Left"],
                sensor_locations_connected_throughout=["Front Left", "Rear Left"],
                findings=[primary],
                top_causes=[primary],
                analysis_metadata={
                    "raw_backed_sample_count": 48,
                    "raw_capture_mode": "raw_backed",
                    "whole_run_context_available": True,
                    "whole_run_context_window_count": 8,
                    "whole_run_context_interval_count": 1,
                    "whole_run_context_full_window_count": 8,
                    "whole_run_context_partial_window_count": 0,
                    "whole_run_context_missing_window_count": 0,
                    "whole_run_context_missing_speed_window_count": 0,
                    "whole_run_context_missing_rpm_window_count": 0,
                    "whole_run_context_stale_speed_window_count": 0,
                    "whole_run_context_stale_rpm_window_count": 0,
                },
                whole_run_context_intervals=[
                    {
                        "segment_index": 0,
                        "phase": "cruise",
                        "load_state": "light",
                        "start_window_index": 0,
                        "end_window_index": 7,
                        "start_t_s": 0.0,
                        "end_t_s": 4.0,
                        "speed_min_kmh": 58.0,
                        "speed_max_kmh": 70.0,
                        "speed_band": "50-70",
                        "full_context_window_count": 8,
                        "partial_context_window_count": 0,
                        "missing_context_window_count": 0,
                    }
                ],
            )
        )
    )

    confidence = prepared.report_facts.confidence
    data = build_report_document(prepared)

    assert confidence.label_key == "CONFIDENCE_HIGH"
    assert confidence.pct_text == "90%"
    assert confidence.tier == "C"
    assert "raw_backed" in confidence.signal_keys
    assert "stable_frequency" in confidence.signal_keys
    assert "localized_support" in confidence.signal_keys
    assert confidence.caveat_keys == ()
    assert data.observed.certainty_label == "High"
    assert "raw-backed replay confirmed the match" in data.observed.certainty_reason
    assert data.verdict_page.proof_snapshot_rows[0].label == "Confidence"


def test_prepare_persisted_report_input_builds_low_confidence_from_mixed_summary_only_signals() -> (
    None
):
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
                run_id="confidence-low",
                lang="en",
                metadata={
                    "run_id": "confidence-low",
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

    confidence = prepared.report_facts.confidence
    data = build_report_document(prepared)

    assert confidence.label_key == "CONFIDENCE_LOW"
    assert "summary_only" in confidence.caveat_keys
    assert "close_alternative" in confidence.caveat_keys
    assert "mixed_support_locations" in confidence.caveat_keys
    assert data.observed.certainty_label == "Low"
    assert "only summary-level evidence was available" in data.observed.certainty_reason
    assert "matched frequency drifted across 12.1-15.6 Hz" in data.observed.certainty_reason
    assert data.verdict_page.also_consider == "Driveline"


def test_prepare_persisted_report_input_adds_whole_run_context_gap_caveats() -> None:
    primary = make_finding_payload(
        finding_id="F_CONTEXT_GAPS",
        suspected_source="wheel/tire",
        confidence=0.78,
        strongest_location="Front Left",
        strongest_speed_band="60-80 km/h",
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
                "location": "Front Left",
                "phase": "cruise",
                "amp": 0.10,
            },
            {
                "t_s": 2.5,
                "speed_kmh": 70.0,
                "predicted_hz": 15.3,
                "matched_hz": 15.3,
                "location": "Front Left",
                "phase": "cruise",
                "amp": 0.09,
            },
        ],
        evidence_metrics={
            "mean_relative_error": 0.03,
            "snr_db": 8.0,
            "matched_samples": 4,
        },
    )
    prepared = prepare_persisted_report_input(
        PersistedAnalysis.from_json_object(
            minimal_summary(
                run_id="context-gaps",
                lang="en",
                metadata={
                    "run_id": "context-gaps",
                    "record_type": "metadata",
                    "schema_version": "v2-jsonl",
                    "feature_interval_s": 0.5,
                },
                sensor_count_used=2,
                sensor_locations=["Front Left", "Rear Left"],
                sensor_locations_connected_throughout=["Front Left", "Rear Left"],
                findings=[primary],
                top_causes=[primary],
                analysis_metadata={
                    "raw_backed_sample_count": 48,
                    "raw_capture_mode": "raw_backed",
                    "whole_run_context_available": True,
                    "whole_run_context_window_count": 12,
                    "whole_run_context_interval_count": 2,
                    "whole_run_context_full_window_count": 9,
                    "whole_run_context_partial_window_count": 2,
                    "whole_run_context_missing_window_count": 1,
                    "whole_run_context_missing_speed_window_count": 1,
                    "whole_run_context_missing_rpm_window_count": 0,
                    "whole_run_context_stale_speed_window_count": 1,
                    "whole_run_context_stale_rpm_window_count": 1,
                },
                whole_run_context_intervals=[
                    {
                        "segment_index": 0,
                        "phase": "cruise",
                        "load_state": "light",
                        "start_window_index": 0,
                        "end_window_index": 7,
                        "start_t_s": 0.0,
                        "end_t_s": 4.0,
                        "speed_min_kmh": 58.0,
                        "speed_max_kmh": 68.0,
                        "speed_band": "50-70",
                        "full_context_window_count": 8,
                        "partial_context_window_count": 0,
                        "missing_context_window_count": 0,
                    },
                    {
                        "segment_index": 1,
                        "phase": "accel",
                        "load_state": "pulling",
                        "start_window_index": 8,
                        "end_window_index": 11,
                        "start_t_s": 4.0,
                        "end_t_s": 6.0,
                        "full_context_window_count": 1,
                        "partial_context_window_count": 2,
                        "missing_context_window_count": 1,
                    },
                ],
            )
        )
    )

    confidence = prepared.report_facts.confidence
    data = build_report_document(prepared)

    assert prepared.report_facts.context.source == "whole_run"
    assert prepared.report_facts.context.has_incomplete_context is True
    assert "speed_context_gaps" in confidence.caveat_keys
    assert "rpm_context_gaps" in confidence.caveat_keys
    assert [warning.code for warning in prepared.report_facts.decision.warnings] == [
        "whole_run_context_incomplete"
    ]
    assert "speed context was missing or stale" in data.observed.certainty_reason
    assert "RPM context was missing or stale" in data.observed.certainty_reason


def test_prepare_persisted_report_input_marks_legacy_raw_backed_context_fallback() -> None:
    primary = make_finding_payload(
        finding_id="F_CONTEXT_LEGACY",
        suspected_source="wheel/tire",
        confidence=0.78,
        strongest_location="Front Left",
        strongest_speed_band="60-80 km/h",
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
                "location": "Front Left",
                "phase": "cruise",
                "amp": 0.10,
            },
            {
                "t_s": 2.5,
                "speed_kmh": 70.0,
                "predicted_hz": 15.3,
                "matched_hz": 15.3,
                "location": "Front Left",
                "phase": "cruise",
                "amp": 0.09,
            },
        ],
        evidence_metrics={
            "mean_relative_error": 0.03,
            "snr_db": 8.0,
            "matched_samples": 4,
        },
    )
    prepared = prepare_persisted_report_input(
        PersistedAnalysis.from_json_object(
            minimal_summary(
                run_id="context-legacy",
                lang="en",
                metadata={
                    "run_id": "context-legacy",
                    "record_type": "metadata",
                    "schema_version": "v2-jsonl",
                    "feature_interval_s": 0.5,
                },
                sensor_count_used=2,
                sensor_locations=["Front Left", "Rear Left"],
                sensor_locations_connected_throughout=["Front Left", "Rear Left"],
                findings=[primary],
                top_causes=[primary],
                analysis_metadata={
                    "raw_backed_sample_count": 48,
                    "raw_capture_mode": "raw_backed",
                },
            )
        )
    )

    confidence = prepared.report_facts.confidence
    data = build_report_document(prepared)

    assert prepared.report_facts.context.source == "legacy"
    assert "legacy_context" in confidence.caveat_keys
    assert "summary_only" not in confidence.caveat_keys
    assert [warning.code for warning in prepared.report_facts.decision.warnings] == [
        "whole_run_context_legacy_fallback"
    ]
    assert "predates whole-run context coverage tracking" in data.observed.certainty_reason
