"""Pure-function tests for vibesensor.use_cases.run.sample_builder.

All helpers tested here are stateless, so no async machinery or database
fixtures are required.  This file focuses on edge cases not covered by the
broader RunRecorder integration tests.
"""

from __future__ import annotations

import pytest

from vibesensor.domain import StrengthMetrics
from vibesensor.use_cases.run.sample_builder import (
    extract_strength_data,
    safe_metric,
)


class TestExtractStrengthData:
    """Tests for extract_strength_data edge cases."""

    def test_empty_metrics_dict_returns_all_nones(self) -> None:
        sm, peaks = extract_strength_data({})

        assert sm == StrengthMetrics()
        assert peaks == []

    def test_top_peaks_with_zero_amp_are_filtered(self) -> None:
        """Peaks with amp ≤ 0 must be excluded from top_peaks output."""
        metrics = {
            "combined": {
                "strength_metrics": {
                    "top_peaks": [
                        {"hz": 100.0, "amp": 0.0},  # should be filtered
                        {"hz": 200.0, "amp": -1.0},  # should be filtered
                        {"hz": 300.0, "amp": 0.5},  # should be kept
                    ],
                },
            },
        }
        sm, peaks = extract_strength_data(metrics)

        assert len(sm.top_peaks) == 3
        assert len(peaks) == 1
        assert peaks[0]["hz"] == 300.0

    def test_combined_reads_nested_strength_metrics(self) -> None:
        """Reads strength_metrics from combined.strength_metrics."""
        metrics = {
            "combined": {
                "strength_metrics": {
                    "peak_amp_g": 0.88,
                },
            },
        }
        sm, _ = extract_strength_data(metrics)

        assert sm == StrengthMetrics(peak_amp_g=0.88)

    def test_invalid_scalar_fields_degrade_to_none_on_typed_metrics(self) -> None:
        sm, peaks = extract_strength_data(
            {
                "combined": {
                    "strength_metrics": {
                        "vibration_strength_db": "bad",
                        "peak_amp_g": float("nan"),
                        "noise_floor_amp_g": "invalid",
                        "top_peaks": [{"hz": 50.0, "amp": 0.2}],
                    },
                },
            },
        )

        assert sm.vibration_strength_db is None
        assert sm.peak_amp_g is None
        assert sm.noise_floor_amp_g is None
        assert sm.dominant_hz == 50.0
        assert peaks == [{"hz": 50.0, "amp": 0.2}]


class TestSafeMetric:
    """Tests for the public safe_metric helper."""

    def test_valid_numeric_is_returned(self) -> None:
        assert safe_metric({"z": {"peak": 0.77}}, "z", "peak") == pytest.approx(0.77)

    def test_missing_axis_returns_none(self) -> None:
        assert safe_metric({"x": {"rms": 0.1}}, "y", "rms") is None

    def test_non_dict_axis_returns_none(self) -> None:
        assert safe_metric({"x": "bad"}, "x", "rms") is None

    def test_nan_value_returns_none(self) -> None:
        assert safe_metric({"x": {"rms": float("nan")}}, "x", "rms") is None

    def test_inf_value_returns_none(self) -> None:
        assert safe_metric({"x": {"rms": float("inf")}}, "x", "rms") is None
