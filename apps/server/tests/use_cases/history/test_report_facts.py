from __future__ import annotations

import pytest
from test_support.findings import make_finding_payload
from test_support.report_helpers import minimal_summary

from vibesensor.shared.boundaries.test_run_reconstruction import (
    test_run_from_summary as build_test_run_from_summary,
)
from vibesensor.shared.run_context_warning import RunContextWarning
from vibesensor.use_cases.history.report_facts import prepare_report_facts


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


def test_prepare_report_facts_filters_to_active_sensor_locations() -> None:
    summary = _summary()
    test_run = build_test_run_from_summary(summary)
    assert test_run is not None

    facts = prepare_report_facts(summary, test_run=test_run)

    assert facts.sensor_locations_active == ("front_left",)
    assert [row.location for row in facts.active_sensor_intensity] == ["front_left"]
    assert facts.sample_rate_hz == "400"
    assert facts.sensor_model == "VS-1"
    assert facts.firmware_version == "1.2.3"


def test_prepare_report_facts_keeps_canonical_warning_models() -> None:
    summary = _summary()
    test_run = build_test_run_from_summary(summary)
    assert test_run is not None

    facts = prepare_report_facts(
        summary,
        test_run=test_run,
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

    assert [warning.code for warning in facts.warnings] == ["PERSISTED_ONLY"]


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
    test_run = build_test_run_from_summary(summary)
    assert test_run is not None

    facts = prepare_report_facts(summary, test_run=test_run)

    assert len(facts.timeline_intervals) == 2
    assert facts.timeline_intervals[0].phase == "cruise"
    assert facts.timeline_intervals[0].speed_max_kmh == 62.0
    assert facts.timeline_intervals[1].phase == "accel"
    assert facts.timeline_intervals[1].has_fault_evidence is True


def test_prepare_report_facts_precomputes_workflow_display_sections() -> None:
    summary = _summary()
    test_run = build_test_run_from_summary(summary)
    assert test_run is not None

    facts = prepare_report_facts(summary, test_run=test_run)

    assert facts.display.verdict.action_status
    assert facts.display.verdict.suspected_source
    assert facts.display.appendix_a.mode == "workflow"
    assert len(facts.display.appendix_a.ranked_candidates) == 1
    assert facts.display.appendix_b.coverage_label == facts.display.verdict.coverage_label
    assert len(facts.display.verdict.footer_routes) == 4


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
    test_run = build_test_run_from_summary(summary)
    assert test_run is not None

    facts = prepare_report_facts(summary, test_run=test_run)
    primary = facts.primary_candidate_facts.domain_primary

    assert primary is not None
    assert primary.confidence_assessment is not None
    assert primary.confidence_assessment.tier == "B"
    assert facts.location_confidence_key == "weak"
    assert facts.action_status_key == "action_ready_caution"


def test_prepare_report_facts_keeps_weak_spatial_wheel_findings_on_recapture_path() -> None:
    summary = _weak_spatial_order_summary(source="wheel/tire", order_label="1x wheel order")
    test_run = build_test_run_from_summary(summary)
    assert test_run is not None

    facts = prepare_report_facts(summary, test_run=test_run)

    assert facts.location_confidence_key == "weak"
    assert facts.action_status_key == "recapture_before_acting"


def test_prepare_report_facts_precomputes_recapture_display_guidance() -> None:
    summary = _weak_spatial_order_summary(source="wheel/tire", order_label="1x wheel order")
    test_run = build_test_run_from_summary(summary)
    assert test_run is not None

    facts = prepare_report_facts(summary, test_run=test_run)

    assert facts.display.appendix_a.mode == "recapture"
    assert facts.display.appendix_a.capture_issues
    assert facts.display.appendix_a.capture_changes
    assert facts.display.appendix_a.capture_conditions
    assert facts.display.verdict.reason_sentence == facts.display.appendix_a.capture_issues[0]
    assert len(facts.display.verdict.footer_routes) == 1
