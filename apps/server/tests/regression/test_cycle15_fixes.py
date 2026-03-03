"""Tests for Cycle 6 (session 3) fixes – a.k.a. cycle-15 in the global sequence.

Covers:
  1. processing._medfilt3 — NaN-safe median via np.nanmedian
  2. processing._resize_buffer — shrink/grow/same-size edge cases
  3. processing._medfilt3 — edge preservation
"""

from __future__ import annotations

import numpy as np
import pytest

from vibesensor.processing import SignalProcessor


def _make_processor(**overrides) -> SignalProcessor:
    defaults = dict(
        sample_rate_hz=100,
        waveform_seconds=1,
        waveform_display_hz=50,
        fft_n=32,
    )
    defaults.update(overrides)
    return SignalProcessor(**defaults)


# ------------------------------------------------------------------
# 1. _medfilt3 — NaN resilience
# ------------------------------------------------------------------


class TestMedfilt3NanResilience:
    """_medfilt3 must not propagate NaN to neighbors of a single NaN sample."""

    def test_single_nan_not_spread(self) -> None:
        proc = _make_processor()
        # 3 axes, 5 samples. One spike at index 2 (a NaN).
        arr = np.array(
            [
                [1.0, 1.0, float("nan"), 1.0, 1.0],
                [2.0, 2.0, 2.0, 2.0, 2.0],
                [3.0, 3.0, 3.0, 3.0, 3.0],
            ],
            dtype=np.float32,
        )
        result = proc._medfilt3(arr)
        # The NaN in axis0 index2 should be replaced by nanmedian of [1,nan,1]=1.0
        assert np.isfinite(result[0, 2]), f"NaN at [0,2] not cleaned: {result[0, 2]}"
        assert result[0, 2] == pytest.approx(1.0)

    def test_short_block_unchanged(self) -> None:
        proc = _make_processor()
        arr = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]], dtype=np.float32)
        result = proc._medfilt3(arr)
        np.testing.assert_array_equal(result, arr)

    def test_edges_preserved(self) -> None:
        proc = _make_processor()
        arr = np.array(
            [
                [10.0, 1.0, 1.0, 1.0, 20.0],
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0],
            ],
            dtype=np.float32,
        )
        result = proc._medfilt3(arr)
        # Edge values should be preserved
        assert result[0, 0] == 10.0
        assert result[0, -1] == 20.0

    def test_spike_removal(self) -> None:
        proc = _make_processor()
        # Normal values with a spike at index 2
        arr = np.array(
            [
                [1.0, 1.0, 100.0, 1.0, 1.0],
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0],
            ],
            dtype=np.float32,
        )
        result = proc._medfilt3(arr)
        # Spike should be replaced by median of [1, 100, 1] = 1.0
        assert result[0, 2] == pytest.approx(1.0)

    def test_all_nan_row_no_crash(self) -> None:
        proc = _make_processor()
        arr = np.full((3, 5), float("nan"), dtype=np.float32)
        result = proc._medfilt3(arr)
        # Should not crash — result is still all NaN but no exception
        assert result.shape == arr.shape


# ------------------------------------------------------------------
# 2. _resize_buffer — edge cases
# ------------------------------------------------------------------


class TestResizeBuffer:
    """_resize_buffer must handle shrink, grow, and same-size correctly."""

    def _make_proc_with_buffer(self):
        proc = _make_processor(sample_rate_hz=100, waveform_seconds=1)
        buf = proc._get_or_create("test-client")
        # Ingest 10 samples
        samples = np.random.default_rng(42).standard_normal((10, 3)).astype(np.float32)
        proc.ingest("test-client", samples)
        return proc, buf

    def test_same_size_noop(self) -> None:
        proc, buf = self._make_proc_with_buffer()
        count_before = buf.count
        proc._resize_buffer(buf, 100)  # same as sample_rate * waveform_seconds
        assert buf.count == count_before
        assert buf.capacity == 100

    def test_grow_preserves_data(self) -> None:
        proc, buf = self._make_proc_with_buffer()
        old_count = buf.count
        proc._resize_buffer(buf, 200)
        assert buf.capacity == 200
        assert buf.count == old_count

    def test_shrink_caps_count(self) -> None:
        proc, buf = self._make_proc_with_buffer()
        proc._resize_buffer(buf, 5)
        assert buf.capacity == 5
        assert buf.count <= 5

    def test_zero_clamped_to_one(self) -> None:
        proc, buf = self._make_proc_with_buffer()
        proc._resize_buffer(buf, 0)
        assert buf.capacity == 1
        assert buf.count <= 1

    def test_negative_clamped_to_one(self) -> None:
        proc, buf = self._make_proc_with_buffer()
        proc._resize_buffer(buf, -10)
        assert buf.capacity == 1
