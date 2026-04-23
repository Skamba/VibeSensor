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
    assert summary.whole_run_order_summaries == ()
    assert summary.whole_run_spatial_summaries == ()


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


def test_report_summary_from_mapping_normalizes_whole_run_order_summaries() -> None:
    summary = report_summary_from_mapping(
        {
            "run_id": "run-123",
            "metadata": {"run_id": "run-123"},
            "whole_run_order_summaries": [
                {
                    "hypothesis_key": "wheel",
                    "suspected_source": "wheel/tire",
                    "order_family": "wheel",
                    "order_label": "wheel family",
                    "total_window_count": 12,
                    "eligible_window_count": 10,
                    "matched_window_count": 8,
                    "support_ratio": 0.8,
                    "reference_coverage_ratio": 0.83,
                    "longest_contiguous_support_window_count": 4,
                    "contiguous_support_ratio": 0.4,
                    "support_intervals": [
                        {
                            "interval_index": 0,
                            "start_window_index": 2,
                            "end_window_index": 5,
                            "matched_window_count": 4,
                            "support_ratio": 1.0,
                            "phase": "cruise",
                        }
                    ],
                    "phase_support": [
                        {
                            "phase": "cruise",
                            "eligible_window_count": 10,
                            "matched_window_count": 8,
                            "support_ratio": 0.8,
                        }
                    ],
                    "harmonic_summaries": [
                        {
                            "harmonic": 1,
                            "order_label": "1x wheel",
                            "eligible_window_count": 10,
                            "matched_window_count": 8,
                            "support_ratio": 0.8,
                            "reference_coverage_ratio": 0.83,
                            "contiguous_support_ratio": 0.4,
                            "lock_score": 0.76,
                            "drift_score": 0.91,
                        }
                    ],
                    "stable_frequency_min_hz": 13.1,
                    "stable_frequency_max_hz": 13.7,
                    "exemplar_interval_index": 0,
                    "dominant_phase": "cruise",
                    "dominant_speed_band": "60-80 km/h",
                    "strongest_location": "front-left",
                    "mean_relative_error": 0.02,
                    "relative_error_stddev": 0.01,
                    "drift_score": 0.91,
                    "lock_score": 0.76,
                    "peak_intensity_db": 18.0,
                    "mean_vibration_strength_db": 11.5,
                    "ref_sources": ["speed+tire"],
                }
            ],
        }
    )

    assert len(summary.whole_run_order_summaries) == 1
    order_summary = summary.whole_run_order_summaries[0]
    assert order_summary.hypothesis_key == "wheel"
    assert order_summary.matched_window_count == 8
    assert order_summary.support_intervals[0].phase == "cruise"
    assert order_summary.phase_support[0].support_ratio == 0.8
    assert order_summary.harmonic_summaries[0].harmonic == 1
    assert order_summary.stable_frequency_min_hz == 13.1
    assert order_summary.ref_sources == ("speed+tire",)


def test_report_summary_from_mapping_normalizes_whole_run_spatial_summaries() -> None:
    summary = report_summary_from_mapping(
        {
            "run_id": "run-123",
            "metadata": {"run_id": "run-123"},
            "whole_run_spatial_summaries": [
                {
                    "candidate_key": "wheel_1x",
                    "suspected_source": "wheel/tire",
                    "proof_basis": "supporting_windows_raw_backed",
                    "total_window_count": 8,
                    "supporting_window_count": 6,
                    "supporting_sensor_count": 2,
                    "coherent_window_count": 4,
                    "coherence_ratio": 0.67,
                    "dominant_location": "front-left",
                    "runner_up_location": "front-right",
                    "location_separation_db": 2.5,
                    "dominance_ratio": 1.5,
                    "ambiguous_location": False,
                    "weak_spatial_separation": False,
                    "location_summaries": [
                        {
                            "location": "front-left",
                            "sensor_ids": ["sensor-front"],
                            "supporting_window_count": 6,
                            "support_ratio": 1.0,
                            "coherent_window_count": 4,
                            "coherence_ratio": 0.67,
                            "peak_intensity_db": 18.0,
                            "mean_vibration_strength_db": 11.5,
                        }
                    ],
                }
            ],
        }
    )

    assert len(summary.whole_run_spatial_summaries) == 1
    spatial_summary = summary.whole_run_spatial_summaries[0]
    assert spatial_summary.candidate_key == "wheel_1x"
    assert spatial_summary.proof_basis == "supporting_windows_raw_backed"
    assert spatial_summary.dominant_location == "front-left"
    assert spatial_summary.location_summaries[0].sensor_ids == ("sensor-front",)


def test_report_summary_requires_connected_active_locations() -> None:
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
