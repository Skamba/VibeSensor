from __future__ import annotations

from math import sqrt

import pytest

import vibesensor.vibration_strength as vibration_strength_module
from vibesensor.vibration_strength import (
    compute_vibration_strength_db,
    median,
    peak_band_rms_amp_g,
    strength_floor_amp_g,
    vibration_strength_db_scalar,
)

# -- median ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        pytest.param([], 0.0, id="empty_returns_zero"),
        pytest.param([7.0], 7.0, id="single_element"),
        pytest.param([3.0, 1.0, 2.0], 2.0, id="odd_count"),
        pytest.param([1.0, 2.0, 3.0, 4.0], 2.5, id="even_count_true_median"),
        pytest.param([1.0, 3.0], 2.0, id="two_elements"),
        pytest.param([4.0, 1.0, 3.0, 2.0], 2.5, id="even_unsorted"),
    ],
)
def test_median(values: list[float], expected: float) -> None:
    assert median(values) == expected


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
    # Remaining values: [0.1, 0.2, 0.3, 0.4] → median = (0.2+0.3)/2 = 0.25
    assert result == pytest.approx(0.25)


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
    assert result == pytest.approx(3.0)


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


def test_floor_rms_skips_broadcast_peak_exclusion_on_sorted_freq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broadcast_calls = 0
    original = vibration_strength_module._peak_exclusion_mask_broadcast_aligned

    def counting_peak_exclusion_mask_broadcast_aligned(**kwargs: object) -> object:
        nonlocal broadcast_calls
        broadcast_calls += 1
        return original(**kwargs)

    monkeypatch.setattr(
        vibration_strength_module,
        "_peak_exclusion_mask_broadcast_aligned",
        counting_peak_exclusion_mask_broadcast_aligned,
    )

    result = strength_floor_amp_g(
        freq_hz=[10.0, 20.0, 30.0, 40.0, 50.0],
        combined_spectrum_amp_g=[0.1, 0.2, 5.0, 0.3, 0.4],
        peak_indexes=[2],
        exclusion_hz=5.0,
        min_hz=0.0,
        max_hz=100.0,
    )

    assert broadcast_calls == 0
    assert result == pytest.approx(0.25)


def test_floor_rms_uses_broadcast_fallback_for_non_monotonic_freq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broadcast_calls = 0
    original = vibration_strength_module._peak_exclusion_mask_broadcast_aligned

    def counting_peak_exclusion_mask_broadcast_aligned(**kwargs: object) -> object:
        nonlocal broadcast_calls
        broadcast_calls += 1
        return original(**kwargs)

    monkeypatch.setattr(
        vibration_strength_module,
        "_peak_exclusion_mask_broadcast_aligned",
        counting_peak_exclusion_mask_broadcast_aligned,
    )

    result = strength_floor_amp_g(
        freq_hz=[10.0, 30.0, 20.0, 40.0, 50.0],
        combined_spectrum_amp_g=[0.1, 5.0, 0.2, 0.3, 0.4],
        peak_indexes=[1],
        exclusion_hz=5.0,
        min_hz=0.0,
        max_hz=100.0,
    )

    assert broadcast_calls == 1
    assert result == pytest.approx(0.25)


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


def test_band_rms_single_bin() -> None:
    result = peak_band_rms_amp_g(
        freq_hz=[10.0],
        combined_spectrum_amp_g=[3.0],
        center_idx=0,
        bandwidth_hz=0.5,
    )
    assert result == pytest.approx(3.0)


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
    assert result == pytest.approx(expected)


def test_band_rms_last_bin_uses_available_neighbors() -> None:
    freq = [8.0, 9.0, 10.0, 11.0, 12.0]
    values = [0.0, 1.0, 2.0, 1.0, 2.0]
    result = peak_band_rms_amp_g(
        freq_hz=freq,
        combined_spectrum_amp_g=values,
        center_idx=4,
        bandwidth_hz=1.5,
    )
    expected = sqrt((1.0 + 4.0) / 2)
    assert result == pytest.approx(expected)


def test_compute_vibration_strength_db_skips_repeated_alignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aligned_calls = 0
    original = vibration_strength_module._aligned_float_arrays

    def counting_aligned_float_arrays(
        left: vibration_strength_module.ArrayLike,
        right: vibration_strength_module.ArrayLike,
    ) -> tuple[
        vibration_strength_module.npt.NDArray[vibration_strength_module.np.float64],
        vibration_strength_module.npt.NDArray[vibration_strength_module.np.float64],
    ]:
        nonlocal aligned_calls
        aligned_calls += 1
        return original(left, right)

    monkeypatch.setattr(
        vibration_strength_module,
        "_aligned_float_arrays",
        counting_aligned_float_arrays,
    )

    result = compute_vibration_strength_db(
        freq_hz=[float(index) for index in range(20)],
        combined_spectrum_amp_g_values=[
            0.001,
            0.001,
            0.001,
            0.001,
            0.001,
            0.002,
            0.004,
            0.01,
            0.03,
            0.06,
            0.12,
            0.03,
            0.01,
            0.004,
            0.002,
            0.001,
            0.001,
            0.001,
            0.001,
            0.001,
        ],
    )

    assert aligned_calls == 0
    assert result["vibration_strength_db"] > 0.0


def test_compute_vibration_strength_db_skips_full_scan_band_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full_scan_calls = 0
    original = vibration_strength_module._peak_band_rms_amp_g_aligned

    def counting_peak_band_rms_amp_g_aligned(**kwargs: object) -> float:
        nonlocal full_scan_calls
        full_scan_calls += 1
        return original(**kwargs)

    monkeypatch.setattr(
        vibration_strength_module,
        "_peak_band_rms_amp_g_aligned",
        counting_peak_band_rms_amp_g_aligned,
    )

    result = compute_vibration_strength_db(
        freq_hz=[float(index) for index in range(20)],
        combined_spectrum_amp_g_values=[
            0.001,
            0.001,
            0.001,
            0.001,
            0.001,
            0.002,
            0.004,
            0.01,
            0.03,
            0.06,
            0.12,
            0.03,
            0.01,
            0.004,
            0.002,
            0.001,
            0.001,
            0.001,
            0.001,
            0.001,
        ],
    )

    assert full_scan_calls == 0
    assert result["vibration_strength_db"] > 0.0


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
