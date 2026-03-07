"""Report signal-filtering and buffer-shape regressions."""

from __future__ import annotations

import numpy as np
import pytest

from vibesensor.processing import SignalProcessor
from vibesensor.processing.fft import medfilt3


def _make_processor(**overrides) -> SignalProcessor:
    defaults = {
        "sample_rate_hz": 100,
        "waveform_seconds": 1,
        "waveform_display_hz": 50,
        "fft_n": 32,
    }
    defaults.update(overrides)
    return SignalProcessor(**defaults)


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


class TestResizeBuffer:
    """_resize_buffer must handle shrink, grow, and same-size correctly."""

    def _make_proc_with_buffer(self):
        proc = _make_processor(sample_rate_hz=100, waveform_seconds=1)
        buf = proc._get_or_create("test-client")
        samples = np.random.default_rng(42).standard_normal((10, 3)).astype(np.float32)
        proc.ingest("test-client", samples)
        return proc, buf

    def test_same_size_noop(self) -> None:
        proc, buf = self._make_proc_with_buffer()
        count_before = buf.count
        proc._resize_buffer(buf, 100)
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

    @pytest.mark.parametrize("new_cap", [0, -10], ids=["zero", "negative"])
    def test_non_positive_clamped_to_one(self, new_cap: int) -> None:
        proc, buf = self._make_proc_with_buffer()
        proc._resize_buffer(buf, new_cap)
        assert buf.capacity == 1
        assert buf.count <= 1
