"""Extended vibration math and metrics coverage tests."""

from __future__ import annotations

from math import log10, sqrt

import pytest
from vibesensor_core.strength_bands import bucket_for_strength
from vibesensor_core.vibration_strength import (
    STRENGTH_EPSILON_FLOOR_RATIO,
    STRENGTH_EPSILON_MIN_G,
    combined_spectrum_amp_g,
    compute_vibration_strength_db,
    vibration_strength_db_scalar,
)

# -- bucket_for_strength exact boundaries ------------------------------------


@pytest.mark.parametrize(
    "db_value,expected",
    [
        (7.999, "l0"),
        (8.0, "l1"),
        (15.999, "l1"),
        (16.0, "l2"),
        (25.999, "l2"),
        (26.0, "l3"),
        (35.999, "l3"),
        (36.0, "l4"),
        (45.999, "l4"),
        (46.0, "l5"),
        (0.0, "l0"),
        (-10.0, "l0"),
        (100.0, "l5"),
    ],
)
def test_bucket_exact_boundaries(db_value: float, expected: str | None) -> None:
    assert bucket_for_strength(db_value) == expected


# -- vibration_strength_db_scalar -------------------------------------------


def test_strength_db_exact_known_value() -> None:
    band = 10.0
    floor = 1.0
    eps = max(STRENGTH_EPSILON_MIN_G, floor * STRENGTH_EPSILON_FLOOR_RATIO)
    expected = 20.0 * log10((band + eps) / (floor + eps))
    result = vibration_strength_db_scalar(
        peak_band_rms_amp_g=band,
        floor_amp_g=floor,
    )
    assert abs(result - expected) < 1e-9


def test_strength_db_both_zero() -> None:
    result = vibration_strength_db_scalar(
        peak_band_rms_amp_g=0.0,
        floor_amp_g=0.0,
    )
    assert abs(result) < 1e-6


def test_strength_db_negative_inputs_clamped() -> None:
    result = vibration_strength_db_scalar(
        peak_band_rms_amp_g=-5.0,
        floor_amp_g=-3.0,
    )
    zero_result = vibration_strength_db_scalar(
        peak_band_rms_amp_g=0.0,
        floor_amp_g=0.0,
    )
    assert abs(result - zero_result) < 1e-9


# -- combined_spectrum_amp_g -------------------------------------------------


def test_combined_spectrum_three_axes_known_values() -> None:
    axes = [[3.0, 0.0], [4.0, 0.0], [0.0, 1.0]]
    result = combined_spectrum_amp_g(axis_spectra_amp_g=axes)
    assert abs(result[0] - sqrt(25.0 / 3)) < 1e-9
    assert abs(result[1] - sqrt(1.0 / 3)) < 1e-9


def test_combined_spectrum_empty() -> None:
    assert combined_spectrum_amp_g(axis_spectra_amp_g=[]) == []


def test_combined_spectrum_single_axis() -> None:
    values = [2.0, 5.0, 7.0]
    result = combined_spectrum_amp_g(axis_spectra_amp_g=[values])
    for orig, computed in zip(values, result, strict=True):
        assert abs(computed - orig) < 1e-9


# -- compute_vibration_strength_db -------------------------------------------


def test_compute_strength_empty_input() -> None:
    result = compute_vibration_strength_db(
        freq_hz=[],
        combined_spectrum_amp_g_values=[],
    )
    assert result["vibration_strength_db"] == 0.0
    assert result["strength_bucket"] is None
    assert result["top_peaks"] == []


def test_compute_strength_single_tone_produces_correct_peak() -> None:
    n = 512
    freq_resolution = 400.0 / n
    freq_hz = [i * freq_resolution for i in range(n)]
    spectrum = [0.001] * n
    # Inject strong tone near 25 Hz
    target_bin = round(25.0 / freq_resolution)
    for offset in (-1, 0, 1):
        idx = target_bin + offset
        if 0 <= idx < n:
            spectrum[idx] = 1.0

    result = compute_vibration_strength_db(
        freq_hz=freq_hz,
        combined_spectrum_amp_g_values=spectrum,
    )
    assert result["vibration_strength_db"] > 5.0
    assert len(result["top_peaks"]) >= 1
    assert abs(result["top_peaks"][0]["hz"] - 25.0) < freq_resolution * 2
