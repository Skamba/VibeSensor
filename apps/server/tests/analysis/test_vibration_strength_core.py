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
    @pytest.mark.parametrize(
        ("values", "expected"),
        [
            pytest.param([], 0.0, id="empty"),
            pytest.param([42.0], 42.0, id="single"),
            pytest.param([1.0, 2.0, 3.0], 2.0, id="odd_count"),
            pytest.param([1.0, 2.0, 3.0, 4.0], 2.5, id="even_count"),
            pytest.param([3.0, 1.0, 2.0], 2.0, id="unsorted"),
        ],
    )
    def test_median(self, values: list[float], expected: float) -> None:
        assert median(values) == expected


# -- percentile ---------------------------------------------------------------


class TestPercentile:
    @pytest.mark.parametrize(
        ("values", "q", "expected"),
        [
            pytest.param([], 0.5, 0.0, id="empty"),
            pytest.param([5.0], 0.5, 5.0, id="single"),
            pytest.param([1.0, 2.0, 3.0], 0.0, 1.0, id="p0_first"),
            pytest.param([1.0, 2.0, 3.0], 1.0, 3.0, id="p100_last"),
            pytest.param([1.0, 2.0, 3.0], 0.5, 2.0, id="p50_middle"),
            pytest.param([1.0, 2.0, 3.0], 1.5, 3.0, id="q_clamped_above_1"),
            pytest.param([1.0, 2.0, 3.0], -0.5, 1.0, id="q_clamped_below_0"),
        ],
    )
    def test_percentile(self, values: list[float], q: float, expected: float) -> None:
        assert percentile(values, q) == expected


# -- combined_spectrum_amp_g --------------------------------------------------


class TestCombinedSpectrumAmpG:
    def test_empty_input(self) -> None:
        assert combined_spectrum_amp_g(axis_spectra_amp_g=[]) == []

    def test_single_axis(self) -> None:
        result = combined_spectrum_amp_g(axis_spectra_amp_g=[[1.0, 2.0, 3.0]])
        # sqrt(v^2 / 1) = v for a single axis
        assert result == pytest.approx([1.0, 2.0, 3.0])

    def test_three_axes_rms(self) -> None:
        result = combined_spectrum_amp_g(
            axis_spectra_amp_g=[[3.0], [4.0], [0.0]],
        )
        # sqrt((9 + 16 + 0) / 3) = sqrt(25/3) ≈ 2.886
        assert result[0] == pytest.approx(math.sqrt(25.0 / 3.0))

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
        assert result[0] == pytest.approx(math.sqrt(25.0 / 3.0))

    def test_empty_axis_array_returns_empty(self) -> None:
        result = combined_spectrum_amp_g(axis_spectra_amp_g=[[]])
        assert result == []


# -- noise_floor_amp_p20_g ---------------------------------------------------


class TestNoiseFloorAmpP20G:
    def test_empty_returns_zero(self) -> None:
        assert noise_floor_amp_p20_g(combined_spectrum_amp_g=[]) == 0.0

    def test_single_value(self) -> None:
        # A single-element input is treated as the DC bin only — there is no
        # AC frequency content to estimate a noise floor from, so 0.0 is correct.
        result = noise_floor_amp_p20_g(combined_spectrum_amp_g=[0.05])
        assert result == 0.0

    def test_skips_dc_bin(self) -> None:
        # First value (DC) is large but should be skipped
        result = noise_floor_amp_p20_g(combined_spectrum_amp_g=[100.0, 0.01, 0.02, 0.03])
        assert result < 1.0  # Should use P20 of [0.01, 0.02, 0.03]

    def test_negative_values_filtered(self) -> None:
        result = noise_floor_amp_p20_g(combined_spectrum_amp_g=[-1.0, -2.0, 0.01, 0.02])
        # Only non-negative finite values are used
        assert result >= 0.0
