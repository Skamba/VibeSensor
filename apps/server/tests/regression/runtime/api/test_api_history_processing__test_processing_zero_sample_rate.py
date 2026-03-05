"""Runtime regressions spanning API, history, and processing boundaries."""

from __future__ import annotations

import re

import numpy as np
import pytest

from vibesensor.processing import SignalProcessor

_SAFE_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


class TestProcessingZeroSampleRate:
    """Processing must not crash when sample_rate_hz is zero."""

    def _make_processor(self, sr: int) -> SignalProcessor:
        return SignalProcessor(
            sample_rate_hz=sr,
            waveform_seconds=4,
            waveform_display_hz=100,
            fft_n=256,
            spectrum_max_hz=200,
        )

    def test_selected_payload_returns_empty_on_zero_sr(self) -> None:
        # Processor with sr=0 but data ingested at a valid rate
        proc = self._make_processor(0)
        raw = np.zeros((10, 3), dtype=np.int16)
        proc.ingest("c1", raw, sample_rate_hz=800)
        # Force buf.sample_rate_hz back to 0 to simulate the bug path
        buf = proc._buffers["c1"]
        buf.sample_rate_hz = 0
        result = proc.selected_payload("c1")
        # Must return without crash; waveform/spectrum/metrics empty
        assert result.get("waveform") == {} or result.get("metrics") == {}

    @pytest.mark.parametrize("sr,expect_empty", [(0, True), (800, False)], ids=["zero", "normal"])
    def test_fft_params(self, sr: int, *, expect_empty: bool) -> None:
        proc = self._make_processor(800)
        freq_slice, valid_idx = proc._fft_params(sr)
        if expect_empty:
            assert len(freq_slice) == 0
            assert len(valid_idx) == 0
        else:
            assert len(freq_slice) > 0
            assert len(valid_idx) > 0
