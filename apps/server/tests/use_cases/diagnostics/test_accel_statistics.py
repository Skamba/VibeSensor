"""Direct behavior tests for acceleration statistics extraction."""

from __future__ import annotations

import math
from typing import Any

import pytest

from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.use_cases.diagnostics.statistics import (
    compute_accel_statistics as _compute_accel_statistics,
)


class TestComputeAccelStatistics:
    """Direct unit tests for _compute_accel_statistics."""

    def test_empty_samples(self) -> None:
        result = _compute_accel_statistics([], "ADXL345")
        assert result["sat_count"] == 0
        assert result["accel_x_vals"] == []
        assert result["accel_mag_vals"] == []

    def test_basic_values(self) -> None:
        samples: list[dict[str, Any]] = [
            {
                "accel_x_g": 0.1,
                "accel_y_g": 0.2,
                "accel_z_g": 1.0,
                "vibration_strength_db": 12.0,
            },
        ]
        result = _compute_accel_statistics(sensor_frames_from_mappings(samples), "ADXL345")
        assert len(result["accel_x_vals"]) == 1
        assert result["accel_x_vals"][0] == pytest.approx(0.1)
        assert len(result["accel_mag_vals"]) == 1
        expected_mag = math.sqrt(0.1**2 + 0.2**2 + 1.0**2)
        assert result["accel_mag_vals"][0] == pytest.approx(expected_mag, rel=1e-3)

    def test_saturation_detected_near_limit(self) -> None:
        samples: list[dict[str, Any]] = [
            {"accel_x_g": 15.7, "accel_y_g": 0.0, "accel_z_g": 0.0},
        ]
        result = _compute_accel_statistics(sensor_frames_from_mappings(samples), "ADXL345")
        assert result["sat_count"] >= 1, "Near-limit value should count as saturation"

    def test_missing_axes_handled(self) -> None:
        samples: list[dict[str, Any]] = [{"accel_x_g": 0.5}]
        result = _compute_accel_statistics(sensor_frames_from_mappings(samples), "unknown")
        assert len(result["accel_x_vals"]) == 1
        assert result["accel_y_vals"] == []
        assert result["accel_mag_vals"] == []

    def test_unknown_sensor_no_saturation_check(self) -> None:
        samples: list[dict[str, Any]] = [
            {"accel_x_g": 999.0, "accel_y_g": 999.0, "accel_z_g": 999.0},
        ]
        result = _compute_accel_statistics(
            sensor_frames_from_mappings(samples),
            "totally_unknown_sensor",
        )
        if result["sensor_limit"] is None:
            assert result["sat_count"] == 0
