"""Noise floor and peak-band RMS on a combined spectrum."""

from __future__ import annotations

from math import sqrt

import pytest

from vibesensor.dsp.vibration_strength import (
    peak_band_rms_amp_g,
    strength_floor_amp_g,
)

# -- strength_floor_amp_g ----------------------------------------------------


@pytest.mark.parametrize(
    ("freq", "values", "peak_indexes", "exclusion_hz", "hz_range", "expected"),
    [
        pytest.param([], [], [], 1.0, (0, 100), 0.0, id="empty-spectrum"),
        # Peak at 30 Hz excluded (+/-5 Hz): median of [0.1, 0.2, 0.3, 0.4].
        pytest.param(
            [10.0, 20.0, 30.0, 40.0, 50.0],
            [0.1, 0.2, 5.0, 0.3, 0.4],
            [2],
            5.0,
            (0, 100),
            0.25,
            id="excludes-peak-region",
        ),
        # Non-monotonic frequencies fall back to the broadcast exclusion mask.
        pytest.param(
            [10.0, 30.0, 20.0, 40.0, 50.0],
            [0.1, 5.0, 0.2, 0.3, 0.4],
            [1],
            5.0,
            (0, 100),
            0.25,
            id="non-monotonic-frequencies",
        ),
        # Only 15/25/35 Hz fall inside [10, 40].
        pytest.param(
            [5.0, 15.0, 25.0, 35.0, 45.0],
            [1.0, 2.0, 3.0, 4.0, 5.0],
            [],
            0.0,
            (10, 40),
            3.0,
            id="respects-min-max-hz",
        ),
        pytest.param(
            [10.0, 20.0], [0.5, 0.6], [99], 1.0, (0, 100), 0.55, id="ignores-bad-peak-index"
        ),
    ],
)
def test_strength_floor_amp_g_cases(
    freq: list[float],
    values: list[float],
    peak_indexes: list[int],
    exclusion_hz: float,
    hz_range: tuple[float, float],
    expected: float,
) -> None:
    result = strength_floor_amp_g(
        freq_hz=freq,
        combined_spectrum_amp_g=values,
        peak_indexes=peak_indexes,
        exclusion_hz=exclusion_hz,
        min_hz=hz_range[0],
        max_hz=hz_range[1],
    )

    assert result == pytest.approx(expected)


# -- peak_band_rms_amp_g ----------------------------------------------------


@pytest.mark.parametrize("center_idx", [-1, 5])
def test_band_rms_center_out_of_range_raises(center_idx: int) -> None:
    with pytest.raises(ValueError, match="center_idx"):
        peak_band_rms_amp_g(
            freq_hz=[10.0],
            combined_spectrum_amp_g=[1.0],
            center_idx=center_idx,
            bandwidth_hz=1.0,
        )


@pytest.mark.parametrize(
    ("freq", "values", "center_idx", "bandwidth_hz", "expected"),
    [
        pytest.param([10.0], [3.0], 0, 0.5, 3.0, id="single-bin"),
        # 10 Hz +/- 1.5 Hz covers 9/10/11 Hz.
        pytest.param(
            [8.0, 9.0, 10.0, 11.0, 12.0],
            [0.0, 1.0, 2.0, 1.0, 0.0],
            2,
            1.5,
            sqrt((1.0 + 4.0 + 1.0) / 3),
            id="multiple-bins",
        ),
        pytest.param(
            [8.0, 9.0, 10.0, 11.0, 12.0],
            [0.0, 1.0, 2.0, 1.0, 2.0],
            4,
            1.5,
            sqrt((1.0 + 4.0) / 2),
            id="last-bin-uses-available-neighbors",
        ),
    ],
)
def test_band_rms_cases(
    freq: list[float],
    values: list[float],
    center_idx: int,
    bandwidth_hz: float,
    expected: float,
) -> None:
    result = peak_band_rms_amp_g(
        freq_hz=freq,
        combined_spectrum_amp_g=values,
        center_idx=center_idx,
        bandwidth_hz=bandwidth_hz,
    )
    assert result == pytest.approx(expected)
