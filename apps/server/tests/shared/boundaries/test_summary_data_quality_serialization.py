from __future__ import annotations

from vibesensor.domain.speed_profile_summary import SpeedProfileSummary
from vibesensor.shared.boundaries.summary_serialization._data_quality import (
    build_data_quality_dict,
)


def test_build_data_quality_dict_counts_missing_required_fields() -> None:
    payload = build_data_quality_dict(
        samples=[
            {"t_s": 0.0, "speed_kmh": 12.0, "accel_x_g": 0.1},
            {"t_s": 1.0, "speed_kmh": None, "accel_y_g": 0.2},
        ],
        speed_values=[12.0],
        speed_stats=SpeedProfileSummary(mean_kmh=12.0, stddev_kmh=0.0),
        speed_non_null_pct=50.0,
        accel_stats={},
        amp_metric_values=[],
    )

    assert payload["required_missing_pct"] == {
        "t_s": 0.0,
        "speed_kmh": 50.0,
        "accel_x": 50.0,
        "accel_y": 50.0,
        "accel_z": 100.0,
    }


def test_build_data_quality_dict_reports_speed_coverage_from_inputs() -> None:
    payload = build_data_quality_dict(
        samples=[{"t_s": 0.0}, {"t_s": 1.0}],
        speed_values=[5.0, 15.0],
        speed_stats=SpeedProfileSummary(mean_kmh=10.0, stddev_kmh=5.0),
        speed_non_null_pct=80.0,
        accel_stats={},
        amp_metric_values=[],
    )

    assert payload["speed_coverage"] == {
        "non_null_pct": 80.0,
        "min_kmh": 5.0,
        "max_kmh": 15.0,
        "mean_kmh": 10.0,
        "stddev_kmh": 5.0,
        "count_non_null": 2,
    }


def test_build_data_quality_dict_builds_outlier_payloads() -> None:
    payload = build_data_quality_dict(
        samples=[{"t_s": 0.0}],
        speed_values=[],
        speed_stats=SpeedProfileSummary(),
        speed_non_null_pct=0.0,
        accel_stats={"accel_mag_vals": [1.0, 1.0, 1.0, 1.0, 10.0]},
        amp_metric_values=[2.0, 2.0, 2.0, 2.0, 20.0],
    )

    assert payload["outliers"]["accel_magnitude"]["count"] == 5
    assert payload["outliers"]["accel_magnitude"]["outlier_count"] == 1
    assert payload["outliers"]["accel_magnitude"]["outlier_pct"] == 20.0
    assert payload["outliers"]["amplitude_metric"]["count"] == 5
    assert payload["outliers"]["amplitude_metric"]["outlier_count"] == 1
    assert payload["outliers"]["amplitude_metric"]["outlier_pct"] == 20.0
