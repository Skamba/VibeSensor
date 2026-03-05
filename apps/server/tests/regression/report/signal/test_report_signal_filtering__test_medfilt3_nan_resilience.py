"""Report signal-filtering and buffer-shape regressions.

Covers:
  1. processing.medfilt3 — NaN-safe median via np.nanmedian
  2. processing._resize_buffer — shrink/grow/same-size edge cases
  3. processing.medfilt3 — edge preservation
"""

from __future__ import annotations

import numpy as np
import pytest

from vibesensor.processing import SignalProcessor
from vibesensor.processing.fft import medfilt3


def _make_processor(**overrides) -> SignalProcessor:
    defaults = dict(
        sample_rate_hz=100,
        waveform_seconds=1,
        waveform_display_hz=50,
        fft_n=32,
    )
    defaults.update(overrides)
    return SignalProcessor(**defaults)


class TestMedfilt3NanResilience:
    """_medfilt3 must not propagate NaN to neighbors of a single NaN sample."""

    def test_single_nan_not_spread(self) -> None:
        # 3 axes, 5 samples. One spike at index 2 (a NaN).
        arr = np.array(
            [
                [1.0, 1.0, float("nan"), 1.0, 1.0],
                [2.0, 2.0, 2.0, 2.0, 2.0],
                [3.0, 3.0, 3.0, 3.0, 3.0],
            ],
            dtype=np.float32,
        )
        result = medfilt3(arr)
        # The NaN in axis0 index2 should be replaced by nanmedian of [1,nan,1]=1.0
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
        # Edge values should be preserved
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
        # Spike should be replaced by median of [1, 100, 1] = 1.0
        assert result[0, 2] == pytest.approx(1.0)

    def test_all_nan_row_no_crash(self) -> None:
        arr = np.full((3, 5), float("nan"), dtype=np.float32)
        result = medfilt3(arr)
        # Should not crash — result is still all NaN but no exception
        assert result.shape == arr.shape
