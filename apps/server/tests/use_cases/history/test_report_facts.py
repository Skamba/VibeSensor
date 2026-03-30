from __future__ import annotations

from test_support.findings import make_finding_payload

from vibesensor.shared.boundaries.test_run_reconstruction import (
    test_run_from_summary as build_test_run_from_summary,
)
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


def test_prepare_report_facts_shapes_warning_payloads() -> None:
    summary = _summary()
    test_run = build_test_run_from_summary(summary)
    assert test_run is not None

    facts = prepare_report_facts(
        summary,
        test_run=test_run,
        warnings=[{"code": "PERSISTED_ONLY", "severity": "warning", "message": "cached"}],
    )

    assert [warning["code"] for warning in facts.warnings] == ["PERSISTED_ONLY"]
