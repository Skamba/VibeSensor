"""Pure-function tests for vibesensor.infra.metrics.sample_builder.

All helpers tested here are stateless, so no async machinery or database
fixtures are required.  This file focuses on edge cases not covered by the
broader RunRecorder integration tests.
"""

from __future__ import annotations

import pytest

from vibesensor.infra.metrics.sample_builder import (
    _parse_peak,
    extract_strength_data,
    safe_metric,
)


class TestParsePeak:
    """Tests for the internal _parse_peak helper."""

    def test_valid_peak_dict_returns_tuple(self) -> None:
        result = _parse_peak({"hz": 123.5, "amp": 0.42})
        assert result == (123.5, 0.42)

    def test_negative_hz_returns_none(self) -> None:
        """A peak with non-positive frequency is physically invalid."""
        assert _parse_peak({"hz": -50.0, "amp": 0.3}) is None

    def test_zero_hz_returns_none(self) -> None:
        assert _parse_peak({"hz": 0.0, "amp": 0.3}) is None

    def test_non_dict_returns_none(self) -> None:
        assert _parse_peak(None) is None
        assert _parse_peak(42) is None
        assert _parse_peak([100.0, 0.5]) is None

    def test_missing_amp_key_returns_none(self) -> None:
        assert _parse_peak({"hz": 100.0}) is None

    def test_nan_amp_returns_none(self) -> None:
        assert _parse_peak({"hz": 100.0, "amp": float("nan")}) is None

    def test_inf_hz_returns_none(self) -> None:
        assert _parse_peak({"hz": float("inf"), "amp": 0.3}) is None


class TestExtractStrengthData:
    """Tests for extract_strength_data edge cases."""

    def test_empty_metrics_dict_returns_all_nones(self) -> None:
        sm, vib_db, bucket, peak_g, floor_g, peaks = extract_strength_data({})

        assert sm == {}
        assert vib_db is None
        assert bucket is None
        assert peak_g is None
        assert floor_g is None
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
        _, _, _, _, _, peaks = extract_strength_data(metrics)

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
        sm, _, _, peak_g, _, _ = extract_strength_data(metrics)

        assert sm == {"peak_amp_g": 0.88}
        assert peak_g == pytest.approx(0.88)


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
