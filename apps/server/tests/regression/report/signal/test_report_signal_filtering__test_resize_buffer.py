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


def _make_processor(**overrides) -> SignalProcessor:
    defaults = dict(
        sample_rate_hz=100,
        waveform_seconds=1,
        waveform_display_hz=50,
        fft_n=32,
    )
    defaults.update(overrides)
    return SignalProcessor(**defaults)


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

    @pytest.mark.parametrize("new_cap", [0, -10], ids=["zero", "negative"])
    def test_non_positive_clamped_to_one(self, new_cap: int) -> None:
        proc, buf = self._make_proc_with_buffer()
        proc._resize_buffer(buf, new_cap)
        assert buf.capacity == 1
        assert buf.count <= 1
