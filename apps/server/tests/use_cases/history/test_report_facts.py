from __future__ import annotations

import pytest
from test_support.findings import make_finding_payload
from test_support.report_helpers import minimal_summary

from vibesensor.shared.boundaries.analysis_payloads.reconstruction import (
    test_run_from_summary as build_test_run_from_summary,
)
from vibesensor.shared.boundaries.reporting import prepare_report_facts, prepare_report_input
from vibesensor.shared.boundaries.reporting.summary import report_summary_from_mapping
from vibesensor.shared.run_context_warning import RunContextWarning
from vibesensor.use_cases.history.report_document import build_report_document


def _summary() -> dict[str, object]:
    finding = make_finding_payload(finding_id="F001")
    return {
        "run_id": "report-facts",
        "file_name": "report-facts.csv",
        "rows": 32,
        "duration_s": 12.5,
        "sensor_count_used": 2,
        "lang": "en",
        "metadata": {
            "run_id": "report-facts",
            "car_info": {"tire_spec": "205/55R16"},
            "sensor_model": "VS-1",
            "firmware_version": "1.2.3",
            "raw_sample_rate_hz": 400,
        },
        "report_date": "",
        "record_length": "12.5 s",
        "start_time_utc": "2026-03-30T12:00:00Z",
        "end_time_utc": "2026-03-30T12:00:12Z",
        "warnings": [],
        "sensor_locations": ["front_left", "rear_right"],
        "sensor_locations_connected_throughout": ["front_left"],
        "sensor_intensity_by_location": [
            {"location": "front_left", "p95_intensity_db": 12.0, "peak_intensity_db": 18.0},
            {"location": "rear_right", "p95_intensity_db": 4.0, "peak_intensity_db": 8.0},
        ],
        "most_likely_origin": {},
        "run_suitability": [],
        "plots": {},
        "test_plan": [],
        "findings": [finding],
        "top_causes": [finding],
    }


def _weak_spatial_order_summary(*, source: str, order_label: str) -> dict[str, object]:
    finding = make_finding_payload(
        finding_id="F_ORDER",
        suspected_source=source,
        confidence=0.65,
        strongest_location="Front Right",
        strongest_speed_band="40-70 km/h",
        frequency_hz_or_order=order_label,
        dominance_ratio=1.04,
        weak_spatial_separation=True,
    )
    return minimal_summary(
        run_id=f"weak-spatial-{source.replace('/', '-')}",
        file_name=f"weak-spatial-{source.replace('/', '-')}.json",
        rows=64,
        sensor_count_used=4,
        lang="en",
        metadata={
            "run_id": f"weak-spatial-{source.replace('/', '-')}",
            "car_info": {"tire_spec": "205/55R16"},
            "sensor_model": "VS-1",
            "firmware_version": "1.2.3",
            "raw_sample_rate_hz": 400,
        },
        report_date="",
        record_length="18.0 s",
        start_time_utc="2026-03-30T12:00:00Z",
        end_time_utc="2026-03-30T12:00:18Z",
        sensor_locations=["front_left", "front_right", "rear_left", "rear_right"],
        sensor_locations_connected_throughout=[
            "front_left",
            "front_right",
            "rear_left",
            "rear_right",
        ],
        sensor_intensity_by_location=[
            {"location": "Front Left", "p95_intensity_db": 15.0, "peak_intensity_db": 18.8},
            {"location": "Front Right", "p95_intensity_db": 18.0, "peak_intensity_db": 22.0},
            {"location": "Rear Left", "p95_intensity_db": 15.4, "peak_intensity_db": 19.1},
            {"location": "Rear Right", "p95_intensity_db": 17.6, "peak_intensity_db": 21.5},
        ],
        findings=[finding],
        top_causes=[finding],
        run_suitability=[
            {
                "check_key": "SUITABILITY_CHECK_FRAME_INTEGRITY",
                "state": "pass",
            },
            {
                "check_key": "SUITABILITY_CHECK_SPEED_VARIATION",
                "state": "pass",
            },
        ],
    )


def _prepare_facts(summary: dict[str, object], **kwargs: object):
    test_run = build_test_run_from_summary(summary)
    assert test_run is not None
    return prepare_report_facts(
        summary,
        summary=report_summary_from_mapping(summary),
        test_run=test_run,
        **kwargs,
    )


def _prepare_document(summary: dict[str, object]):
    return build_report_document(prepare_report_input(summary))


def test_prepare_report_facts_filters_to_active_sensor_locations() -> None:
    summary = _summary()
    facts = _prepare_facts(summary)

    assert facts.sensor.active_locations == ("front_left",)
    assert [row.location for row in facts.sensor.active_intensity] == ["front_left"]
    assert facts.run.sample_rate_hz == "400"
    assert facts.run.sensor_model == "VS-1"
    assert facts.run.firmware_version == "1.2.3"


def test_prepare_report_facts_prefers_supporting_window_location_proof() -> None:
    primary = make_finding_payload(
        finding_id="F_LOCATION_PROOF",
        suspected_source="wheel/tire",
        confidence=0.81,
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
                "predicted_hz": 15.2,
                "matched_hz": 15.2,
                "location": "Front Left",
                "phase": "cruise",
                "amp": 0.10,
            },
            {
                "t_s": 2.0,
                "speed_kmh": 68.0,
                "predicted_hz": 15.4,
                "matched_hz": 15.3,
                "location": "Rear Left",
                "phase": "cruise",
                "amp": 0.03,
            },
        ],
    )
    summary = minimal_summary(
        run_id="supporting-window-location-proof",
        lang="en",
        sensor_count_used=2,
        sensor_locations=["Front Left", "Rear Left"],
        sensor_locations_connected_throughout=["Front Left", "Rear Left"],
        sensor_intensity_by_location=[
            {"location": "Front Left", "p95_intensity_db": 11.0, "peak_intensity_db": 16.0},
            {"location": "Rear Left", "p95_intensity_db": 24.0, "peak_intensity_db": 30.0},
        ],
        findings=[primary],
        top_causes=[primary],
        analysis_metadata={
            "raw_capture_available": True,
            "raw_backed_sample_count": 24,
            "raw_capture_mode": "raw_backed",
        },
    )

    facts = _prepare_facts(summary)

    assert facts.sensor.location_hotspot_rows[0].location == "Rear Left"
    assert facts.sensor.proof_basis == "supporting_windows_raw_backed"
    assert [row.location for row in facts.sensor.proof_intensity] == ["Front Left", "Rear Left"]
    assert facts.sensor.proof_location_hotspot_rows[0].location == "Front Left"


def test_prepare_report_facts_keeps_canonical_warning_models() -> None:
    summary = _summary()
    facts = _prepare_facts(
        summary,
        warnings=[
            RunContextWarning(
                code="PERSISTED_ONLY",
                severity="warn",
                applies_to="report",
                title="Cached warning",
                detail="cached",
            )
        ],
    )

    assert [warning.code for warning in facts.decision.warnings] == ["PERSISTED_ONLY"]


def test_prepare_report_facts_keeps_phase_timeline_intervals() -> None:
    summary = _summary()
    summary["phase_timeline"] = [
        {
            "phase": "cruise",
            "start_t_s": 0.0,
            "end_t_s": 3.0,
            "speed_min_kmh": 58.0,
            "speed_max_kmh": 62.0,
            "has_fault_evidence": False,
        },
        {
            "phase": "accel",
            "start_t_s": 3.0,
            "end_t_s": 6.5,
            "speed_min_kmh": 62.0,
            "speed_max_kmh": 78.0,
            "has_fault_evidence": True,
        },
    ]
    facts = _prepare_facts(summary)

    assert len(facts.run.timeline_intervals) == 2
    assert facts.run.timeline_intervals[0].phase == "cruise"
    assert facts.run.timeline_intervals[0].speed_max_kmh == 62.0
    assert facts.run.timeline_intervals[1].phase == "accel"
    assert facts.run.timeline_intervals[1].has_fault_evidence is True


def test_prepare_report_facts_projects_whole_run_context_facts_from_persisted_analysis() -> None:
    summary = _summary()
    summary["analysis_metadata"] = {
        "raw_backed_sample_count": 24,
        "raw_capture_mode": "raw_backed",
        "whole_run_context_available": True,
        "whole_run_context_window_count": 6,
        "whole_run_context_interval_count": 2,
        "whole_run_context_full_window_count": 4,
        "whole_run_context_partial_window_count": 1,
        "whole_run_context_missing_window_count": 1,
        "whole_run_context_missing_speed_window_count": 1,
        "whole_run_context_missing_rpm_window_count": 0,
        "whole_run_context_stale_speed_window_count": 0,
        "whole_run_context_stale_rpm_window_count": 1,
    }
    summary["whole_run_context_intervals"] = [
        {
            "segment_index": 0,
            "phase": "cruise",
            "load_state": "light",
            "start_window_index": 0,
            "end_window_index": 2,
            "start_t_s": 0.0,
            "end_t_s": 1.5,
            "speed_min_kmh": 58.0,
            "speed_max_kmh": 62.0,
            "speed_band": "50-70",
            "full_context_window_count": 3,
            "partial_context_window_count": 0,
            "missing_context_window_count": 0,
        },
        {
            "segment_index": 1,
            "phase": "accel",
            "load_state": "pulling",
            "start_window_index": 3,
            "end_window_index": 5,
            "start_t_s": 1.5,
            "end_t_s": 3.0,
            "full_context_window_count": 1,
            "partial_context_window_count": 1,
            "missing_context_window_count": 1,
        },
    ]

    facts = _prepare_facts(summary)

    assert facts.context.traceable is True
    assert facts.context.source == "whole_run"
    assert facts.context.interval_count == 2
    assert facts.context.window_count == 6
    assert facts.context.has_incomplete_context is True
    assert facts.context.has_speed_gaps is True
    assert facts.context.has_rpm_gaps is True
    assert len(facts.context.intervals) == 2
    assert facts.context.intervals[0].phase == "cruise"
    assert facts.context.intervals[1].missing_context_window_count == 1
    assert [warning.code for warning in facts.decision.warnings] == ["whole_run_context_incomplete"]


def test_build_report_document_builds_workflow_document_sections() -> None:
    summary = _summary()
    document = _prepare_document(summary)

    assert document.verdict_page.action_status
    assert document.verdict_page.suspected_source
    assert document.appendix_a.mode == "workflow"
    assert len(document.appendix_a.ranked_candidates) == 1
    assert document.appendix_b.coverage_label == document.verdict_page.coverage_label
    assert len(document.verdict_page.footer_routes) == 4
    assert document.traceability_rows


@pytest.mark.parametrize(
    ("source", "order_label"),
    [
        pytest.param("engine", "2x engine order", id="engine"),
        pytest.param("driveline", "1x driveshaft order", id="driveline"),
    ],
)
def test_prepare_report_facts_keeps_weak_spatial_system_order_findings_on_caution_path(
    source: str,
    order_label: str,
) -> None:
    summary = _weak_spatial_order_summary(source=source, order_label=order_label)
    facts = _prepare_facts(summary)
    primary = facts.decision.primary_candidate.domain_primary

    assert primary is not None
    assert primary.confidence_assessment is not None
    assert primary.confidence_assessment.tier == "B"
    assert facts.decision.location_confidence_key == "weak"
    assert facts.decision.action_status_key == "action_ready_caution"


def test_prepare_report_facts_keeps_weak_spatial_wheel_findings_on_recapture_path() -> None:
    summary = _weak_spatial_order_summary(source="wheel/tire", order_label="1x wheel order")
    facts = _prepare_facts(summary)

    assert facts.decision.location_confidence_key == "weak"
    assert facts.decision.action_status_key == "recapture_before_acting"


def test_build_report_document_builds_recapture_document_guidance() -> None:
    summary = _weak_spatial_order_summary(source="wheel/tire", order_label="1x wheel order")
    document = _prepare_document(summary)

    assert document.appendix_a.mode == "recapture"
    assert document.appendix_a.capture_issues
    assert document.appendix_a.capture_changes
    assert document.appendix_a.capture_conditions
    assert document.verdict_page.reason_sentence == document.appendix_a.capture_issues[0]
    assert len(document.verdict_page.footer_routes) == 1
