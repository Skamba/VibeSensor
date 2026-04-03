from __future__ import annotations

import pytest

from vibesensor.shared.boundaries.persisted_analysis_codec import (
    persisted_analysis_from_json_object,
)
from vibesensor.shared.boundaries.reporting import prepare_persisted_report_input
from vibesensor.use_cases.history.report_document import (
    prepare_report_input,
    resolve_primary_report_candidate,
)


def test_prepare_report_input_prefers_connected_sensor_locations() -> None:
    prepared = prepare_report_input(
        {
            "lang": "en",
            "metadata": {},
            "report_date": "",
            "record_length": "",
            "start_time_utc": "",
            "end_time_utc": "",
            "findings": [],
            "top_causes": [],
            "sensor_locations": ["front-left", "rear-right"],
            "sensor_locations_connected_throughout": ["rear-right"],
            "speed_stats": {},
            "most_likely_origin": {},
            "run_suitability": [],
        },
    )
    assert prepared.summary.active_sensor_locations == ("rear-right",)
    assert prepared.report_facts.sensor_locations_active == ("rear-right",)
    assert not hasattr(prepared, "renderer_payload")


def test_resolve_primary_report_candidate_keeps_summary_confidence_context() -> None:
    prepared = prepare_report_input(
        {
            "sensor_count_used": 0,
            "sensor_intensity_by_location": [{"p95_intensity_db": 21.0}],
            "lang": "en",
            "metadata": {},
            "report_date": "",
            "record_length": "",
            "start_time_utc": "",
            "end_time_utc": "",
            "findings": [
                {
                    "finding_id": "F001",
                    "suspected_source": "wheel/tire",
                    "strongest_location": "front-left",
                    "strongest_speed_band": "50-80 km/h",
                    "confidence": 0.71,
                    "evidence_metrics": {"vibration_strength_db": 21.0},
                },
            ],
            "top_causes": [
                {
                    "finding_id": "F001",
                    "suspected_source": "wheel/tire",
                    "strongest_location": "front-left",
                    "strongest_speed_band": "50-80 km/h",
                    "confidence": 0.71,
                },
            ],
            "speed_stats": {"steady_speed": False},
            "most_likely_origin": {},
            "sensor_locations": [],
            "sensor_locations_connected_throughout": [],
            "run_suitability": [],
        },
    )

    def tr(key: str, **_kw: object) -> str:
        return key

    primary = resolve_primary_report_candidate(
        aggregate=prepared.domain_test_run,
        facts=prepared.report_facts.primary_candidate_facts,
        tr=tr,
        lang="en",
    )

    assert primary.primary_system
    assert primary.primary_location == "front-left"
    assert primary.strength_db == 21.0
    assert primary.tier in {"B", "C"}


def test_prepare_persisted_report_input_does_not_roundtrip_through_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = persisted_analysis_from_json_object(
        {
            "run_id": "persisted-run",
            "lang": "en",
            "metadata": {
                "run_id": "persisted-run",
                "active_car_snapshot": {"name": "Track Car", "type": "coupe"},
            },
            "report_date": "2026-03-23T07:31:01Z",
            "record_length": "5m",
            "rows": 120,
            "duration_s": 300.0,
            "sensor_count_used": 2,
            "sensor_locations": ["front-left", "rear-right"],
            "sensor_locations_connected_throughout": ["front-left"],
            "sensor_intensity_by_location": [],
            "most_likely_origin": {},
            "run_suitability": [],
            "test_plan": [],
            "findings": [],
            "top_causes": [],
            "plots": {"peaks_table": [{"rank": 1, "strength_db": 12.0}]},
            "warnings": [
                {
                    "code": "PERSISTED_ONLY",
                    "severity": "warn",
                    "applies_to": "report",
                    "title": "Persisted warning",
                    "detail": "cached",
                }
            ],
        }
    )

    prepared = prepare_persisted_report_input(analysis)

    assert prepared.summary.run_id == "persisted-run"
    assert [warning.code for warning in prepared.report_facts.warnings] == ["PERSISTED_ONLY"]


def test_prepare_persisted_report_input_uses_persisted_reconstruction_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import vibesensor.shared.boundaries.reporting.preparation as report_preparation

    analysis = persisted_analysis_from_json_object(
        {
            "run_id": "persisted-run",
            "lang": "en",
            "metadata": {
                "run_id": "persisted-run",
                "active_car_snapshot": {"name": "Track Car", "type": "coupe"},
            },
            "report_date": "2026-03-23T07:31:01Z",
            "record_length": "5m",
            "rows": 120,
            "duration_s": 300.0,
            "sensor_count_used": 2,
            "sensor_locations": ["front-left", "rear-right"],
            "sensor_locations_connected_throughout": ["front-left"],
            "sensor_intensity_by_location": [],
            "most_likely_origin": {},
            "run_suitability": [],
            "test_plan": [],
            "findings": [],
            "top_causes": [],
            "warnings": [],
        }
    )

    def _explode(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("prepare_persisted_report_input should not use test_run_from_summary")

    monkeypatch.setattr(report_preparation, "report_test_run_from_summary", _explode)

    prepared = report_preparation.prepare_persisted_report_input(analysis)

    assert prepared.domain_test_run is not None
    assert prepared.domain_test_run.capture.run_id == "persisted-run"


def test_prepare_report_input_tolerates_invalid_count_strings() -> None:
    prepared = prepare_report_input(
        {
            "run_id": "bad-counts",
            "rows": "not-a-number",
            "sensor_count_used": "",
            "lang": "en",
            "metadata": {},
            "report_date": "",
            "record_length": "",
            "start_time_utc": "",
            "end_time_utc": "",
            "findings": [],
            "top_causes": [],
            "sensor_locations": [],
            "sensor_locations_connected_throughout": [],
            "speed_stats": {},
            "most_likely_origin": {},
            "run_suitability": [],
        }
    )

    assert prepared.summary.sample_count == 0
    assert prepared.summary.sensor_count == 0
