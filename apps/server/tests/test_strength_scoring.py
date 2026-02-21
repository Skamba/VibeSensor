from __future__ import annotations

from math import sqrt

from vibesensor_core.vibration_strength import (
    median,
    peak_band_rms_amp_g,
    strength_floor_amp_g,
    vibration_strength_db_scalar,
)

# -- median ------------------------------------------------------------------


def test_median_empty_returns_zero() -> None:
    assert median([]) == 0.0


def test_median_single_element() -> None:
    assert median([7.0]) == 7.0


def test_median_odd_count() -> None:
    assert median([3.0, 1.0, 2.0]) == 2.0


def test_median_even_count_uses_lower_middle() -> None:
    # Implementation picks index len//2 for even-length lists (not average).
    result = median([1.0, 2.0, 3.0, 4.0])
    assert result == 3.0  # sorted[4//2] == sorted[2]


# -- strength_floor_amp_g ----------------------------------------------------


def test_floor_rms_empty_freq_returns_zero() -> None:
    assert (
        strength_floor_amp_g(
            freq_hz=[],
            combined_spectrum_amp_g=[],
            peak_indexes=[],
            exclusion_hz=1.0,
            min_hz=0,
            max_hz=100,
        )
        == 0.0
    )


def test_floor_rms_excludes_peak_region() -> None:
    freq = [10.0, 20.0, 30.0, 40.0, 50.0]
    values = [0.1, 0.2, 5.0, 0.3, 0.4]
    # Peak at index 2 (30 Hz); exclude ±5 Hz around it.
    result = strength_floor_amp_g(
        freq_hz=freq,
        combined_spectrum_amp_g=values,
        peak_indexes=[2],
        exclusion_hz=5.0,
        min_hz=0,
        max_hz=100,
    )
    # Remaining values: [0.1, 0.2, 0.3, 0.4] → median = sorted[2] = 0.3
    assert abs(result - 0.3) < 1e-9


def test_floor_rms_respects_min_max_hz() -> None:
    freq = [5.0, 15.0, 25.0, 35.0, 45.0]
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    # Only keep Hz in [10, 40]
    result = strength_floor_amp_g(
        freq_hz=freq,
        combined_spectrum_amp_g=values,
        peak_indexes=[],
        exclusion_hz=0.0,
        min_hz=10,
        max_hz=40,
    )
    # Remaining: [2.0, 3.0, 4.0] → median = sorted[1] = 3.0
    assert abs(result - 3.0) < 1e-9


def test_floor_rms_peak_index_out_of_range_ignored() -> None:
    freq = [10.0, 20.0]
    values = [0.5, 0.6]
    result = strength_floor_amp_g(
        freq_hz=freq,
        combined_spectrum_amp_g=values,
        peak_indexes=[99],
        exclusion_hz=1.0,
        min_hz=0,
        max_hz=100,
    )
    # Bad index ignored → median of [0.5, 0.6]
    assert result > 0


# -- peak_band_rms_amp_g ----------------------------------------------------


def test_band_rms_center_out_of_range_returns_zero() -> None:
    assert (
        peak_band_rms_amp_g(
            freq_hz=[10.0],
            combined_spectrum_amp_g=[1.0],
            center_idx=5,
            bandwidth_hz=1.0,
        )
        == 0.0
    )


def test_band_rms_single_bin() -> None:
    result = peak_band_rms_amp_g(
        freq_hz=[10.0],
        combined_spectrum_amp_g=[3.0],
        center_idx=0,
        bandwidth_hz=0.5,
    )
    assert abs(result - 3.0) < 1e-9


def test_band_rms_multiple_bins() -> None:
    freq = [8.0, 9.0, 10.0, 11.0, 12.0]
    values = [0.0, 1.0, 2.0, 1.0, 0.0]
    result = peak_band_rms_amp_g(
        freq_hz=freq,
        combined_spectrum_amp_g=values,
        center_idx=2,
        bandwidth_hz=1.5,
    )
    # Center 10 Hz ± 1.5 Hz → bins 9, 10, 11 → values 1.0, 2.0, 1.0
    expected = sqrt((1.0 + 4.0 + 1.0) / 3)
    assert abs(result - expected) < 1e-9


# -- vibration_strength_db_scalar --------------------------------------------


def test_strength_db_equal_band_and_floor() -> None:
    # When band_rms == floor_rms the result should be ~0 dB
    db = vibration_strength_db_scalar(
        peak_band_rms_amp_g=1.0,
        floor_amp_g=1.0,
    )
    assert abs(db) < 0.01


def test_strength_db_band_much_above_floor() -> None:
    db = vibration_strength_db_scalar(
        peak_band_rms_amp_g=10.0,
        floor_amp_g=1.0,
    )
    assert db > 15.0  # ~20 dB


def test_strength_db_floor_zero_returns_finite() -> None:
    db = vibration_strength_db_scalar(
        peak_band_rms_amp_g=1e-6,
        floor_amp_g=0.0,
    )
    assert db > 0
    assert db < 200
