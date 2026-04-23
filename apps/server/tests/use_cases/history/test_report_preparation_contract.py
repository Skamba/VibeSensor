from __future__ import annotations

from dataclasses import replace

import pytest
from test_support.findings import make_finding_payload

from vibesensor.shared.boundaries.reporting import (
    prepare_persisted_report_input,
    prepare_report_input,
)
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.use_cases.history.report_document import (
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
    assert prepared.report_facts.sensor.active_locations == ("rear-right",)
    assert not hasattr(prepared, "renderer_payload")


def test_prepare_report_input_rejects_blank_filename() -> None:
    prepared = prepare_report_input(
        {
            "run_id": "blank-filename",
            "lang": "en",
            "metadata": {"run_id": "blank-filename"},
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
        },
    )

    with pytest.raises(ValueError, match="filename must be non-empty"):
        replace(prepared, filename=" ")


def test_prepare_report_input_rejects_run_id_mismatch() -> None:
    prepared = prepare_report_input(
        {
            "run_id": "prepared-run",
            "lang": "en",
            "metadata": {"run_id": "prepared-run"},
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
        },
    )

    with pytest.raises(ValueError, match="run_id mismatch"):
        replace(
            prepared,
            report_facts=replace(
                prepared.report_facts,
                run=replace(prepared.report_facts.run, run_id="other-run"),
            ),
        )


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
        facts=prepared.report_facts.decision.primary_candidate,
        confidence_facts=prepared.report_facts.confidence,
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
    analysis = PersistedAnalysis.from_json_object(
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

    assert prepared.report_facts.run.run_id == "persisted-run"
    assert [warning.code for warning in prepared.report_facts.decision.warnings] == [
        "PERSISTED_ONLY"
    ]


def test_prepare_persisted_report_input_uses_persisted_reconstruction_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import vibesensor.shared.boundaries.reporting.preparation as report_preparation

    analysis = PersistedAnalysis.from_json_object(
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

    monkeypatch.setattr(report_preparation, "test_run_from_summary", _explode)

    prepared = report_preparation.prepare_persisted_report_input(analysis)

    assert prepared.domain_test_run is not None
    assert prepared.domain_test_run.capture.run_id == "persisted-run"


def test_prepare_persisted_report_input_falls_back_to_metadata_run_id() -> None:
    analysis = PersistedAnalysis.from_json_object(
        {
            "lang": "en",
            "metadata": {
                "run_id": "metadata-run",
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

    prepared = prepare_persisted_report_input(analysis)

    assert prepared.report_facts.run.run_id == "metadata-run"
    assert prepared.domain_test_run.capture.run_id == "metadata-run"


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

    assert prepared.report_facts.run.sample_count == 0
    assert prepared.report_facts.run.sensor_count == 0


def test_prepare_report_input_does_not_invent_traceable_whole_run_context() -> None:
    prepared = prepare_report_input(
        {
            "run_id": "implicit-context",
            "rows": 24,
            "sensor_count_used": 2,
            "lang": "en",
            "metadata": {"run_id": "implicit-context"},
            "report_date": "",
            "record_length": "",
            "start_time_utc": "",
            "end_time_utc": "",
            "findings": [],
            "top_causes": [],
            "sensor_locations": ["front-left", "rear-right"],
            "sensor_locations_connected_throughout": ["front-left", "rear-right"],
            "most_likely_origin": {},
            "run_suitability": [],
            "whole_run_context_intervals": [
                {
                    "segment_index": 0,
                    "phase": "cruise",
                    "load_state": "light",
                    "start_window_index": 0,
                    "end_window_index": 3,
                    "full_context_window_count": 4,
                    "partial_context_window_count": 0,
                    "missing_context_window_count": 0,
                }
            ],
        }
    )

    assert prepared.report_facts.context.traceable is False
    assert prepared.report_facts.context.source == "implicit"
    assert prepared.report_facts.context.intervals == ()
    assert prepared.report_facts.decision.warnings == ()


def test_prepare_persisted_report_input_builds_evidence_facts_from_raw_backed_summary() -> None:
    primary = make_finding_payload(
        finding_id="F_PRIMARY",
        suspected_source="wheel/tire",
        confidence=0.76,
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
                "predicted_hz": 15.3,
                "matched_hz": 15.4,
                "location": "Rear Left",
                "phase": "cruise",
                "amp": 0.09,
            },
        ],
    )
    analysis = PersistedAnalysis.from_json_object(
        {
            "run_id": "persisted-run",
            "lang": "en",
            "metadata": {
                "run_id": "persisted-run",
                "record_type": "metadata",
                "schema_version": "v2-jsonl",
                "start_time_utc": "2026-03-23T07:31:01Z",
                "sensor_model": "ADXL345",
                "raw_sample_rate_hz": 800,
                "feature_interval_s": 0.5,
                "fft_window_size_samples": 256,
                "peak_picker_method": "fft",
                "incomplete_for_order_analysis": False,
            },
            "report_date": "2026-03-23T07:31:01Z",
            "record_length": "5m",
            "rows": 120,
            "duration_s": 300.0,
            "sensor_count_used": 2,
            "sensor_locations": ["Front Left", "Rear Left"],
            "sensor_locations_connected_throughout": ["Front Left", "Rear Left"],
            "sensor_intensity_by_location": [],
            "most_likely_origin": {},
            "run_suitability": [],
            "test_plan": [],
            "findings": [primary],
            "top_causes": [primary],
            "warnings": [],
            "analysis_metadata": {
                "raw_capture_available": True,
                "raw_backed_sample_count": 24,
                "raw_capture_mode": "raw_backed",
            },
        }
    )

    prepared = prepare_persisted_report_input(analysis)

    assert prepared.report_facts.evidence.data_basis == "raw_backed"
    assert prepared.report_facts.evidence.raw_backed_sample_count == 24
    assert prepared.report_facts.evidence.supporting_window_count == 3
    assert prepared.report_facts.evidence.supporting_duration_s == pytest.approx(1.5)
    assert prepared.report_facts.evidence.stable_frequency_min_hz == pytest.approx(15.1)
    assert prepared.report_facts.evidence.stable_frequency_max_hz == pytest.approx(15.4)
    assert prepared.report_facts.evidence.supporting_location_counts == (
        ("Front Left", 2),
        ("Rear Left", 1),
    )
