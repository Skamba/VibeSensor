"""Direct unit tests for combined_spectrum_amp_g and noise_floor_amp_p20_g."""

from __future__ import annotations

import math

import pytest
from vibesensor_core.vibration_strength import (
    combined_spectrum_amp_g,
    median,
    noise_floor_amp_p20_g,
    percentile,
)

# -- median -------------------------------------------------------------------


class TestMedian:
    def test_empty_returns_zero(self) -> None:
        assert median([]) == 0.0

    def test_single_value(self) -> None:
        assert median([42.0]) == 42.0

    def test_odd_count(self) -> None:
        assert median([1.0, 2.0, 3.0]) == 2.0

    def test_even_count(self) -> None:
        assert median([1.0, 2.0, 3.0, 4.0]) == 2.5

    def test_unsorted_input(self) -> None:
        assert median([3.0, 1.0, 2.0]) == 2.0


# -- percentile ---------------------------------------------------------------


class TestPercentile:
    def test_empty_returns_zero(self) -> None:
        assert percentile([], 0.5) == 0.0

    def test_single_value(self) -> None:
        assert percentile([5.0], 0.5) == 5.0

    def test_p0_returns_first(self) -> None:
        assert percentile([1.0, 2.0, 3.0], 0.0) == 1.0

    def test_p100_returns_last(self) -> None:
        assert percentile([1.0, 2.0, 3.0], 1.0) == 3.0

    def test_p50_returns_middle(self) -> None:
        assert percentile([1.0, 2.0, 3.0], 0.5) == 2.0

    def test_q_clamped_above_1(self) -> None:
        assert percentile([1.0, 2.0, 3.0], 1.5) == 3.0

    def test_q_clamped_below_0(self) -> None:
        assert percentile([1.0, 2.0, 3.0], -0.5) == 1.0


# -- combined_spectrum_amp_g --------------------------------------------------


class TestCombinedSpectrumAmpG:
    def test_empty_input(self) -> None:
        assert combined_spectrum_amp_g(axis_spectra_amp_g=[]) == []

    def test_single_axis(self) -> None:
        result = combined_spectrum_amp_g(axis_spectra_amp_g=[[1.0, 2.0, 3.0]])
        assert len(result) == 3
        # sqrt(1^2 / 1) = 1.0, sqrt(4/1) = 2.0, sqrt(9/1) = 3.0
        assert abs(result[0] - 1.0) < 1e-9
        assert abs(result[1] - 2.0) < 1e-9
        assert abs(result[2] - 3.0) < 1e-9

    def test_three_axes_rms(self) -> None:
        result = combined_spectrum_amp_g(
            axis_spectra_amp_g=[[3.0], [4.0], [0.0]],
        )
        # sqrt((9 + 16 + 0) / 3) = sqrt(25/3) ≈ 2.886
        expected = math.sqrt(25.0 / 3.0)
        assert abs(result[0] - expected) < 1e-9

    def test_mismatched_lengths_uses_minimum(self) -> None:
        result = combined_spectrum_amp_g(
            axis_spectra_amp_g=[[1.0, 2.0], [3.0]],
        )
        assert len(result) == 1

    def test_axis_count_for_mean_override(self) -> None:
        result = combined_spectrum_amp_g(
            axis_spectra_amp_g=[[3.0], [4.0]],
            axis_count_for_mean=3,
        )
        # sqrt((9 + 16) / 3) = sqrt(25/3)
        expected = math.sqrt(25.0 / 3.0)
        assert abs(result[0] - expected) < 1e-9

    def test_empty_axis_array_returns_empty(self) -> None:
        result = combined_spectrum_amp_g(axis_spectra_amp_g=[[]])
        assert result == []


# -- noise_floor_amp_p20_g ---------------------------------------------------


class TestNoiseFloorAmpP20G:
    def test_empty_returns_zero(self) -> None:
        assert noise_floor_amp_p20_g(combined_spectrum_amp_g=[]) == 0.0

    def test_single_value(self) -> None:
        result = noise_floor_amp_p20_g(combined_spectrum_amp_g=[0.05])
        assert result == pytest.approx(0.05)

    def test_skips_dc_bin(self) -> None:
        # First value (DC) is large but should be skipped
        result = noise_floor_amp_p20_g(combined_spectrum_amp_g=[100.0, 0.01, 0.02, 0.03])
        assert result < 1.0  # Should use P20 of [0.01, 0.02, 0.03]

    def test_negative_values_filtered(self) -> None:
        result = noise_floor_amp_p20_g(combined_spectrum_amp_g=[-1.0, -2.0, 0.01, 0.02])
        # Only non-negative finite values are used
        assert result >= 0.0
