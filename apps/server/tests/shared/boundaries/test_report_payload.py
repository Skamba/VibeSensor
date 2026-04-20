"""Tests for the canonical report payload boundary."""

from __future__ import annotations

import pytest

from vibesensor.shared.boundaries.reporting.summary import (
    has_projectable_report_payload,
    report_summary_from_mapping,
    require_projectable_report_payload,
)


def test_has_projectable_report_payload_accepts_findings_list() -> None:
    assert has_projectable_report_payload({"findings": []}) is True


def test_has_projectable_report_payload_accepts_top_causes_list() -> None:
    assert has_projectable_report_payload({"top_causes": []}) is True


def test_has_projectable_report_payload_rejects_missing_projection_lists() -> None:
    assert has_projectable_report_payload({"run_id": "no-projection"}) is False


def test_has_projectable_report_payload_rejects_non_list_projection_values() -> None:
    assert has_projectable_report_payload({"findings": {}, "top_causes": None}) is False


def test_require_projectable_report_payload_raises_for_non_projectable_payload() -> None:
    with pytest.raises(
        ValueError,
        match="Report payload must include findings or top_causes lists for report preparation",
    ):
        require_projectable_report_payload({"run_id": "no-projection"})


def test_report_summary_from_mapping_defaults_without_nested_metadata() -> None:
    summary = report_summary_from_mapping({})

    assert summary.run_id == "unknown"
    assert summary.metadata is None
    assert summary.report_date is None
    assert summary.duration_s is None
    assert summary.sample_count == 0
    assert summary.sensor_count == 0
    assert summary.active_sensor_locations == ()
    assert summary.sensor_intensity_rows == ()
    assert summary.peak_table_rows == ()
    assert summary.timeline_intervals == ()


def test_report_summary_from_mapping_projects_canonical_metadata_and_rows() -> None:
    summary = report_summary_from_mapping(
        {
            "run_id": "run-123",
            "report_date": " 2026-03-25T10:00:00Z ",
            "duration_s": "12.5",
            "rows": "18",
            "sensor_count_used": "3",
            "metadata": {
                "run_id": "run-123",
                "active_car_snapshot": {"name": "Track Car", "type": "coupe"},
                "recorded_utc_offset_seconds": "7200",
            },
            "sensor_locations_connected_throughout": [" front-left ", "", "rear-right"],
            "sensor_intensity_by_location": [
                {"location": "front-left", "p95_intensity_db": 12.0},
                {"location": "rear-right", "p95_intensity_db": 8.5},
            ],
            "plots": {"peaks_table": [{"rank": 1, "strength_db": 12.0}]},
            "phase_timeline": [
                {
                    "phase": " cruise ",
                    "start_t_s": "0.0",
                    "end_t_s": 3.0,
                    "speed_min_kmh": "58.0",
                    "speed_max_kmh": 62.0,
                    "has_fault_evidence": False,
                }
            ],
        }
    )

    assert summary.run_id == "run-123"
    assert summary.metadata is not None
    assert summary.metadata.car_name == "Track Car"
    assert summary.metadata.recorded_utc_offset_seconds == 7200
    assert summary.report_date == "2026-03-25T10:00:00Z"
    assert summary.duration_s == 12.5
    assert summary.sample_count == 18
    assert summary.sensor_count == 3
    assert summary.active_sensor_locations == ("front-left", "rear-right")
    assert [row.location for row in summary.sensor_intensity_rows] == [
        "front-left",
        "rear-right",
    ]
    assert summary.peak_table_rows == ({"rank": 1, "strength_db": 12.0},)
    assert len(summary.timeline_intervals) == 1
    assert summary.timeline_intervals[0].phase == "cruise"
    assert summary.timeline_intervals[0].speed_min_kmh == 58.0


def test_report_summary_from_mapping_ignores_sensor_locations_without_connected_throughout() -> None:
    summary = report_summary_from_mapping(
        {
            "sensor_locations": ["front-left", "rear-right"],
        }
    )

    assert summary.active_sensor_locations == ()


def test_report_summary_from_mapping_drops_non_finite_summary_scalars() -> None:
    summary = report_summary_from_mapping(
        {
            "duration_s": float("inf"),
            "rows": float("nan"),
            "sensor_count_used": float("-inf"),
            "phase_timeline": [
                {
                    "phase": "cruise",
                    "start_t_s": float("nan"),
                    "end_t_s": float("inf"),
                    "speed_min_kmh": float("-inf"),
                    "speed_max_kmh": float("nan"),
                }
            ],
        }
    )

    assert summary.duration_s is None
    assert summary.sample_count == 0
    assert summary.sensor_count == 0
    assert len(summary.timeline_intervals) == 1
    assert summary.timeline_intervals[0].start_t_s is None
    assert summary.timeline_intervals[0].end_t_s is None
    assert summary.timeline_intervals[0].speed_min_kmh is None
    assert summary.timeline_intervals[0].speed_max_kmh is None


def test_report_summary_from_mapping_rejects_nonempty_metadata_without_nested_run_id() -> None:
    with pytest.raises(
        ValueError, match="report summary metadata must include canonical nested run_id"
    ):
        report_summary_from_mapping(
            {
                "run_id": "run-123",
                "metadata": {"active_car_snapshot": {"name": "Track Car"}},
            }
        )


def test_report_summary_from_mapping_rejects_mismatched_nested_run_id() -> None:
    with pytest.raises(
        ValueError, match="report summary metadata run_id must match the top-level run_id"
    ):
        report_summary_from_mapping(
            {
                "run_id": "run-123",
                "metadata": {
                    "run_id": "other-run",
                    "active_car_snapshot": {"name": "Track Car"},
                },
            }
        )
