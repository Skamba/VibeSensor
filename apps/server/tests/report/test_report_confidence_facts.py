from __future__ import annotations

from test_support.findings import make_finding_payload
from test_support.report_helpers import minimal_summary

from vibesensor.domain.diagnosis_assessment import LEGACY_CONTEXT_CAVEAT_KEY
from vibesensor.report import i18n as report_i18n
from vibesensor.report.document.builder import build_report_document
from vibesensor.report.preparation import prepare_persisted_report_input
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis


def _tr(key: str, **kwargs: object) -> str:
    return report_i18n.tr("en", key, **kwargs)


_STABLE_WHEEL_POINTS = [
    {
        "t_s": 1.0 + 0.5 * index,
        "speed_kmh": 64.0 + 2.0 * index,
        "predicted_hz": predicted_hz,
        "matched_hz": matched_hz,
        "location": "Front Left",
        "phase": "cruise",
        "amp": amp,
    }
    for index, (predicted_hz, matched_hz, amp) in enumerate(
        [(15.0, 15.1, 0.11), (15.1, 15.2, 0.10), (15.2, 15.2, 0.10), (15.3, 15.3, 0.09)]
    )
]


def _stable_front_left_wheel_finding(finding_id: str) -> dict[str, object]:
    """A well-localised wheel/tire finding with four tightly matched cruise points."""
    return make_finding_payload(
        finding_id=finding_id,
        suspected_source="wheel/tire",
        confidence=0.78,
        strongest_location="Front Left",
        strongest_speed_band="60-80 km/h",
        matched_points=_STABLE_WHEEL_POINTS,
        evidence_metrics={"mean_relative_error": 0.03, "snr_db": 8.0, "matched_samples": 4},
    )


def _summary(run_id: str, **overrides: object) -> dict[str, object]:
    return minimal_summary(
        run_id=run_id,
        lang="en",
        metadata={
            "run_id": run_id,
            "record_type": "metadata",
            "schema_version": "v2-jsonl",
            "feature_interval_s": 0.5,
        },
        **overrides,
    )


def _prepare(summary: dict[str, object]):
    return prepare_persisted_report_input(PersistedAnalysis.from_json_object(summary))


def test_prepare_persisted_report_input_builds_high_confidence_from_raw_backed_signals() -> None:
    primary = _stable_front_left_wheel_finding("F_CONFIDENT")
    prepared = _prepare(
        _summary(
            "confidence-high",
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
                    "load_state": "steady",
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

    confidence = prepared.report_facts.confidence
    data = build_report_document(prepared)

    assert confidence.label_key == "CONFIDENCE_HIGH"
    assert confidence.pct_text == "90%"
    assert confidence.tier == "C"
    assert "raw_backed" in confidence.signal_keys
    assert "stable_frequency" in confidence.signal_keys
    assert "localized_support" in confidence.signal_keys
    assert confidence.caveat_keys == ()
    assert confidence.raw_backed_sample_count == 48
    assert confidence.top_support_location == "Front Left"
    assert data.observed.certainty_label == _tr(confidence.label_key)
    assert data.observed.certainty_reason
    assert data.verdict_page.proof_snapshot_rows[0].label == _tr("CONFIDENCE_LABEL")


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
    prepared = _prepare(
        _summary(
            "confidence-low",
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

    confidence = prepared.report_facts.confidence
    data = build_report_document(prepared)

    assert confidence.label_key == "CONFIDENCE_LOW"
    assert "summary_only" in confidence.caveat_keys
    assert "close_alternative" in confidence.caveat_keys
    assert "mixed_support_locations" in confidence.caveat_keys
    assert data.observed.certainty_label == _tr(confidence.label_key)
    assert confidence.stable_frequency_min_hz == 12.1
    assert confidence.stable_frequency_max_hz == 15.6
    assert data.observed.certainty_reason
    assert data.verdict_page.also_consider == "Driveline"


def test_prepare_persisted_report_input_adds_whole_run_context_gap_caveats() -> None:
    primary = _stable_front_left_wheel_finding("F_CONTEXT_GAPS")
    prepared = _prepare(
        _summary(
            "context-gaps",
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
                    "load_state": "steady",
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
                    "phase": "acceleration",
                    "load_state": "transient",
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

    confidence = prepared.report_facts.confidence
    data = build_report_document(prepared)

    assert prepared.report_facts.context.source == "whole_run"
    assert prepared.report_facts.context.has_incomplete_context is True
    assert "speed_context_gaps" in confidence.caveat_keys
    assert "rpm_context_gaps" in confidence.caveat_keys
    assert [warning.code for warning in prepared.report_facts.decision.warnings] == [
        "whole_run_context_incomplete"
    ]
    assert _tr("REPORT_CONFIDENCE_CAVEAT_SPEED_CONTEXT_GAPS") in data.observed.certainty_reason
    assert _tr("REPORT_CONFIDENCE_CAVEAT_RPM_CONTEXT_GAPS") in data.observed.certainty_reason


def test_prepare_persisted_report_input_marks_legacy_raw_backed_context_fallback() -> None:
    primary = _stable_front_left_wheel_finding("F_CONTEXT_LEGACY")
    prepared = _prepare(
        _summary(
            "context-legacy",
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

    confidence = prepared.report_facts.confidence
    data = build_report_document(prepared)

    assert prepared.report_facts.context.source == "legacy"
    assert LEGACY_CONTEXT_CAVEAT_KEY in confidence.caveat_keys
    assert "summary_only" not in confidence.caveat_keys
    assert [warning.code for warning in prepared.report_facts.decision.warnings] == [
        "whole_run_context_legacy_fallback"
    ]
    assert _tr("REPORT_CONFIDENCE_CAVEAT_LEGACY_CONTEXT") in data.observed.certainty_reason
