"""Tests for lightweight report-payload projection helper functions."""

from __future__ import annotations

from vibesensor.shared.boundaries.report_payload_projection import (
    active_sensor_locations,
    coerce_count,
    peak_table_rows,
    phase_timeline_payload,
    report_duration_s,
    sensor_intensity_payload,
    summary_run_metadata,
)


def test_summary_run_metadata_defaults_to_none_without_mapping() -> None:
    assert summary_run_metadata({}) is None
    assert summary_run_metadata({"metadata": "not-a-dict"}) is None


def test_summary_run_metadata_projects_canonical_run_metadata() -> None:
    metadata = summary_run_metadata(
        {
            "run_id": "run-123",
            "metadata": {
                "active_car_snapshot": {"name": "Track Car", "type": "coupe"},
                "analysis_settings_snapshot": {
                    "tire_width_mm": 245.0,
                    "tire_aspect_pct": 40.0,
                    "rim_in": 18.0,
                },
            },
        }
    )

    assert metadata is not None
    assert metadata.run_id == "run-123"
    assert metadata.car_name == "Track Car"
    assert metadata.order_reference_spec is not None


def test_active_sensor_locations_prefers_connected_locations() -> None:
    payload = {
        "sensor_locations_connected_throughout": [" front-left ", "", "rear-right"],
        "sensor_locations": ["fallback-only"],
    }

    assert active_sensor_locations(payload) == ("front-left", "rear-right")


def test_active_sensor_locations_falls_back_to_sensor_locations() -> None:
    payload = {
        "sensor_locations_connected_throughout": [],
        "sensor_locations": [" front-left ", "", "rear-right"],
    }

    assert active_sensor_locations(payload) == ("front-left", "rear-right")


def test_report_duration_s_returns_none_for_invalid_values() -> None:
    assert report_duration_s({}) is None
    assert report_duration_s({"duration_s": "bad"}) is None
    assert report_duration_s({"duration_s": "12.5"}) == 12.5


def test_peak_table_rows_returns_only_mapping_rows() -> None:
    payload = {
        "plots": {
            "peaks_table": [
                {"rank": 1, "strength_db": 12.0},
                "skip-me",
                {"rank": 2, "strength_db": 8.5},
            ]
        }
    }

    rows = peak_table_rows(payload)

    assert rows == (
        {"rank": 1, "strength_db": 12.0},
        {"rank": 2, "strength_db": 8.5},
    )


def test_sensor_intensity_payload_defaults_to_empty_tuple() -> None:
    assert sensor_intensity_payload({}) == ()
    assert sensor_intensity_payload({"sensor_intensity_by_location": "bad"}) == ()


def test_sensor_intensity_payload_returns_tuple_copy() -> None:
    payload = {"sensor_intensity_by_location": [{"location": "front-left"}]}

    assert sensor_intensity_payload(payload) == ({"location": "front-left"},)


def test_phase_timeline_payload_returns_only_mapping_rows() -> None:
    payload = {
        "phase_timeline": [
            {
                "phase": "cruise",
                "start_t_s": 0.0,
                "end_t_s": 3.0,
                "speed_min_kmh": 58.0,
                "speed_max_kmh": 62.0,
                "has_fault_evidence": False,
            },
            "skip-me",
            {
                "phase": "cruise",
                "start_t_s": 3.0,
                "end_t_s": 6.0,
                "speed_min_kmh": 60.0,
                "speed_max_kmh": 64.0,
                "has_fault_evidence": True,
            },
        ]
    }

    assert phase_timeline_payload(payload) == (
        {
            "phase": "cruise",
            "start_t_s": 0.0,
            "end_t_s": 3.0,
            "speed_min_kmh": 58.0,
            "speed_max_kmh": 62.0,
            "has_fault_evidence": False,
        },
        {
            "phase": "cruise",
            "start_t_s": 3.0,
            "end_t_s": 6.0,
            "speed_min_kmh": 60.0,
            "speed_max_kmh": 64.0,
            "has_fault_evidence": True,
        },
    )


def test_coerce_count_defaults_invalid_values_to_zero() -> None:
    assert coerce_count(None) == 0
    assert coerce_count("bad") == 0
    assert coerce_count("17") == 17
