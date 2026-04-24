from __future__ import annotations

from test_support.findings import make_finding_payload
from test_support.report_helpers import minimal_summary

from vibesensor.shared.boundaries.reporting import prepare_persisted_report_input
from vibesensor.shared.json_utils import i18n_ref
from vibesensor.shared.run_context_warning import (
    WARNING_CODE_RAW_REPLAY_COVERAGE_INCOMPLETE,
    WARNING_CODE_RAW_REPLAY_DROPPED_CHUNKS,
    WARNING_CODE_RAW_REPLAY_SYNC_UNVERIFIED,
    WARNING_CODE_RAW_REPLAY_TIMING_FALLBACK,
    WARNING_CODE_WHOLE_RUN_ALIGNMENT_INCOMPLETE,
)
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.use_cases.history.report_document import build_report_document


def test_prepare_persisted_report_input_surfaces_partial_raw_replay_honestly() -> None:
    primary = make_finding_payload(
        finding_id="F_PARTIAL_RAW",
        suspected_source="wheel/tire",
        confidence=0.86,
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
                "amp": 0.10,
            },
            {
                "t_s": 1.5,
                "speed_kmh": 66.0,
                "predicted_hz": 15.0,
                "matched_hz": 15.0,
                "location": "Front Left",
                "phase": "cruise",
                "amp": 0.11,
            },
        ],
        evidence_metrics={
            "mean_relative_error": 0.03,
            "snr_db": 7.5,
            "matched_samples": 2,
        },
    )
    prepared = prepare_persisted_report_input(
        PersistedAnalysis.from_json_object(
            minimal_summary(
                run_id="partial-raw-report",
                lang="en",
                metadata={
                    "run_id": "partial-raw-report",
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
                    "raw_backed_sample_count": 6,
                    "raw_capture_mode": "partial_raw_backed",
                },
                warnings=[
                    {
                        "code": WARNING_CODE_RAW_REPLAY_COVERAGE_INCOMPLETE,
                        "severity": "warn",
                        "applies_to": "raw_replay",
                        "title": i18n_ref("RUN_CONTEXT_WARNING_RAW_REPLAY_INCOMPLETE_TITLE"),
                        "detail": i18n_ref(
                            "RUN_CONTEXT_WARNING_RAW_REPLAY_INCOMPLETE_DETAIL",
                            partial="1",
                            missing="0",
                            gaps="1",
                            overlaps="0",
                            mismatches="0",
                            unverified_rates="0",
                        ),
                    }
                ],
            )
        )
    )

    document = build_report_document(prepared)

    assert prepared.report_facts.evidence.data_basis == "partial_raw_backed"
    assert "raw_replay_incomplete" in prepared.report_facts.confidence.caveat_keys
    assert WARNING_CODE_RAW_REPLAY_COVERAGE_INCOMPLETE in [
        warning.code for warning in prepared.report_facts.decision.warnings
    ]
    assert any(
        "Partially raw-backed replay" in row.value
        for row in document.verdict_page.proof_snapshot_rows
    )
    assert "raw capture coverage was incomplete for some replay windows" in (
        document.observed.certainty_reason
    )


def test_prepare_persisted_report_input_surfaces_legacy_sample_timing_warning() -> None:
    primary = make_finding_payload(
        finding_id="F_TIMING_FALLBACK",
        suspected_source="wheel/tire",
        confidence=0.81,
        strongest_location="Front Left",
        strongest_speed_band="60-80 km/h",
    )
    prepared = prepare_persisted_report_input(
        PersistedAnalysis.from_json_object(
            minimal_summary(
                run_id="timing-fallback-report",
                lang="en",
                metadata={
                    "run_id": "timing-fallback-report",
                    "record_type": "metadata",
                    "schema_version": "v2-jsonl",
                    "feature_interval_s": 0.5,
                },
                sensor_count_used=1,
                sensor_locations=["Front Left"],
                sensor_locations_connected_throughout=["Front Left"],
                findings=[primary],
                top_causes=[primary],
                analysis_metadata={
                    "raw_backed_sample_count": 4,
                    "raw_capture_mode": "raw_backed",
                    "raw_replay_timing_fallback_count": 2,
                },
                warnings=[
                    {
                        "code": WARNING_CODE_RAW_REPLAY_TIMING_FALLBACK,
                        "severity": "warn",
                        "applies_to": "raw_replay",
                        "title": i18n_ref("RUN_CONTEXT_WARNING_RAW_REPLAY_TIMING_FALLBACK_TITLE"),
                        "detail": i18n_ref(
                            "RUN_CONTEXT_WARNING_RAW_REPLAY_TIMING_FALLBACK_DETAIL",
                            count="2",
                        ),
                    }
                ],
            )
        )
    )

    assert WARNING_CODE_RAW_REPLAY_TIMING_FALLBACK in [
        warning.code for warning in prepared.report_facts.decision.warnings
    ]


def test_prepare_persisted_report_input_surfaces_dropped_raw_chunk_warning() -> None:
    primary = make_finding_payload(
        finding_id="F_DROPPED_CHUNKS",
        suspected_source="wheel/tire",
        confidence=0.78,
        strongest_location="Front Left",
        strongest_speed_band="60-80 km/h",
    )
    prepared = prepare_persisted_report_input(
        PersistedAnalysis.from_json_object(
            minimal_summary(
                run_id="dropped-chunks-report",
                lang="en",
                metadata={
                    "run_id": "dropped-chunks-report",
                    "record_type": "metadata",
                    "schema_version": "v2-jsonl",
                    "feature_interval_s": 0.5,
                },
                sensor_count_used=1,
                sensor_locations=["Front Left"],
                sensor_locations_connected_throughout=["Front Left"],
                findings=[primary],
                top_causes=[primary],
                analysis_metadata={
                    "raw_backed_sample_count": 4,
                    "raw_capture_mode": "partial_raw_backed",
                    "raw_replay_dropped_chunk_count": 4,
                    "raw_replay_udp_ingest_queue_drop_count": 1,
                    "raw_replay_queue_overflow_chunk_count": 2,
                    "raw_replay_invalid_chunk_count": 1,
                    "raw_replay_write_error_chunk_count": 0,
                },
                warnings=[
                    {
                        "code": WARNING_CODE_RAW_REPLAY_DROPPED_CHUNKS,
                        "severity": "warn",
                        "applies_to": "raw_replay",
                        "title": i18n_ref("RUN_CONTEXT_WARNING_RAW_REPLAY_DROPPED_CHUNKS_TITLE"),
                        "detail": i18n_ref(
                            "RUN_CONTEXT_WARNING_RAW_REPLAY_DROPPED_CHUNKS_DETAIL",
                            count="4",
                            udp_ingest="1",
                            queue_overflow="2",
                            invalid="1",
                            write_errors="0",
                        ),
                    }
                ],
            )
        )
    )

    document = build_report_document(prepared)

    assert WARNING_CODE_RAW_REPLAY_DROPPED_CHUNKS in [
        warning.code for warning in prepared.report_facts.decision.warnings
    ]
    assert any("UDP ingest queue drops" in (row.detail or "") for row in document.data_trust)


def test_prepare_persisted_report_input_surfaces_sync_unverified_warning() -> None:
    primary = make_finding_payload(
        finding_id="F_STALE_SYNC",
        suspected_source="wheel/tire",
        confidence=0.75,
        strongest_location="Front Left",
        strongest_speed_band="60-80 km/h",
    )
    prepared = prepare_persisted_report_input(
        PersistedAnalysis.from_json_object(
            minimal_summary(
                run_id="stale-sync-report",
                lang="en",
                metadata={
                    "run_id": "stale-sync-report",
                    "record_type": "metadata",
                    "schema_version": "v2-jsonl",
                    "feature_interval_s": 0.5,
                },
                sensor_count_used=1,
                sensor_locations=["Front Left"],
                sensor_locations_connected_throughout=["Front Left"],
                findings=[primary],
                top_causes=[primary],
                analysis_metadata={
                    "raw_backed_sample_count": 0,
                    "raw_capture_mode": "summary_only",
                    "raw_replay_sync_unverified_sensor_count": 1,
                    "raw_replay_stale_sync_sensor_count": 1,
                },
                warnings=[
                    {
                        "code": WARNING_CODE_RAW_REPLAY_SYNC_UNVERIFIED,
                        "severity": "warn",
                        "applies_to": "raw_replay",
                        "title": i18n_ref("RUN_CONTEXT_WARNING_RAW_REPLAY_SYNC_UNVERIFIED_TITLE"),
                        "detail": i18n_ref(
                            "RUN_CONTEXT_WARNING_RAW_REPLAY_SYNC_UNVERIFIED_DETAIL",
                            sensors="1",
                            missing_sync="0",
                            stale="1",
                            high_rtt="0",
                        ),
                    }
                ],
            )
        )
    )

    assert WARNING_CODE_RAW_REPLAY_SYNC_UNVERIFIED in [
        warning.code for warning in prepared.report_facts.decision.warnings
    ]


def test_prepare_persisted_report_input_surfaces_whole_run_alignment_warning() -> None:
    primary = make_finding_payload(
        finding_id="F_WHOLE_RUN_ALIGNMENT",
        suspected_source="wheel/tire",
        confidence=0.79,
        strongest_location="Front Left",
        strongest_speed_band="60-80 km/h",
    )
    prepared = prepare_persisted_report_input(
        PersistedAnalysis.from_json_object(
            minimal_summary(
                run_id="whole-run-alignment-report",
                lang="en",
                metadata={
                    "run_id": "whole-run-alignment-report",
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
                    "raw_backed_sample_count": 8,
                    "raw_capture_mode": "partial_raw_backed",
                    "whole_run_spectral_available": True,
                    "whole_run_spectral_window_count": 4,
                    "whole_run_spectral_partial_sensor_window_count": 1,
                    "whole_run_spectral_missing_sensor_window_count": 1,
                    "whole_run_spectral_gap_count": 1,
                    "whole_run_spectral_sample_rate_mismatch_sensor_count": 1,
                    "whole_run_spectral_sample_rate_unverified_sensor_count": 0,
                    "whole_run_spectral_sync_unverified_sensor_count": 1,
                },
                warnings=[
                    {
                        "code": WARNING_CODE_WHOLE_RUN_ALIGNMENT_INCOMPLETE,
                        "severity": "warn",
                        "applies_to": "whole_run",
                        "title": i18n_ref(
                            "RUN_CONTEXT_WARNING_WHOLE_RUN_ALIGNMENT_INCOMPLETE_TITLE"
                        ),
                        "detail": i18n_ref(
                            "RUN_CONTEXT_WARNING_WHOLE_RUN_ALIGNMENT_INCOMPLETE_DETAIL",
                            partial="1",
                            missing="1",
                            gaps="1",
                            overlaps="0",
                            dropped="0",
                            udp_ingest="0",
                            queue_overflow="0",
                            invalid="0",
                            write_errors="0",
                            mismatches="1",
                            unverified_rates="0",
                            legacy="0",
                            unanchored="0",
                            sync_unverified="1",
                            missing_sync="1",
                            stale="0",
                            high_rtt="0",
                        ),
                    }
                ],
            )
        )
    )

    document = build_report_document(prepared)

    assert WARNING_CODE_WHOLE_RUN_ALIGNMENT_INCOMPLETE in [
        warning.code for warning in prepared.report_facts.decision.warnings
    ]
    assert any(
        "Whole-run raw coverage was incomplete for some time-aligned windows" in (row.detail or "")
        for row in document.data_trust
    )
