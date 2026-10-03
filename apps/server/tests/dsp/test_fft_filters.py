"""DSP filter and noise-floor helpers: NaN-safe median filter and P20 noise floor."""

from __future__ import annotations

import numpy as np
import pytest

from vibesensor.dsp.fft_analysis import medfilt3, noise_floor


class TestMedfilt3NanResilience:
    """_medfilt3 must not propagate NaN to neighbors of a single NaN sample."""

    def test_single_nan_not_spread(self) -> None:
        arr = np.array(
            [
                [1.0, 1.0, float("nan"), 1.0, 1.0],
                [2.0, 2.0, 2.0, 2.0, 2.0],
                [3.0, 3.0, 3.0, 3.0, 3.0],
            ],
            dtype=np.float32,
        )
        result = medfilt3(arr)
        assert np.isfinite(result[0, 2]), f"NaN at [0,2] not cleaned: {result[0, 2]}"
        assert result[0, 2] == pytest.approx(1.0)

    def test_short_block_unchanged(self) -> None:
        arr = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]], dtype=np.float32)
        result = medfilt3(arr)
        np.testing.assert_array_equal(result, arr)

    def test_edges_preserved(self) -> None:
        arr = np.array(
            [
                [10.0, 1.0, 1.0, 1.0, 20.0],
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0],
            ],
            dtype=np.float32,
        )
        result = medfilt3(arr)
        assert result[0, 0] == 10.0
        assert result[0, -1] == 20.0

    def test_spike_removal(self) -> None:
        arr = np.array(
            [
                [1.0, 1.0, 100.0, 1.0, 1.0],
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0],
            ],
            dtype=np.float32,
        )
        result = medfilt3(arr)
        assert result[0, 2] == pytest.approx(1.0)

    def test_all_nan_row_no_crash(self) -> None:
        arr = np.full((3, 5), float("nan"), dtype=np.float32)
        result = medfilt3(arr)
        assert result.shape == arr.shape


class TestNoiseFloorNoDoubleRemoval:
    """Regression: _noise_floor must not skip amps[1:] before delegating
    to noise_floor_amp_p20_g, since the caller already provides the
    analysis-band slice (DC already removed).
    """

    def test_all_bins_included(self) -> None:
        amps = np.array([0.010, 0.012, 0.009, 0.011, 0.013], dtype=np.float32)
        floor = noise_floor(amps)
        # All 5 bins should be considered. If amps[1:] were used,
        # the first bin (0.010) would be excluded, changing the result.
        # P20 of [0.009, 0.010, 0.011, 0.012, 0.013] ≈ 0.0098
        assert floor > 0.0
        # The result must include the first bin. If it were excluded,
        # P20 of [0.011, 0.012, 0.013] = 0.0114, which is higher.
        # With all 5 bins, P20 is lower because 0.009 and 0.010 pull it down.
        floor_without_first = noise_floor(amps[1:])
        assert floor <= floor_without_first + 1e-6, (
            f"Floor {floor} should be ≤ floor-without-first {floor_without_first}"
        )
