"""Behavior tests for multi-spectrum alignment payloads."""

from __future__ import annotations

import math
from math import pi

import numpy as np

from vibesensor.infra.processing import SignalProcessor


def _proc(**kwargs) -> SignalProcessor:
    defaults = {
        "sample_rate_hz": 800,
        "waveform_seconds": 4,
        "waveform_display_hz": 100,
        "fft_n": 512,
        "spectrum_max_hz": 200,
    }
    defaults.update(kwargs)
    return SignalProcessor(**defaults)


def _inject(proc: SignalProcessor, cid: str, n: int = 1024, sr: int = 800) -> None:
    rng = np.random.default_rng(42)
    t = np.arange(n, dtype=np.float64) / sr
    x = (0.03 * np.sin(2.0 * pi * 30.0 * t)).astype(np.float32)
    y = (0.02 * np.sin(2.0 * pi * 50.0 * t)).astype(np.float32)
    z = (rng.standard_normal(n) * 0.005).astype(np.float32)
    samples = np.stack([x, y, z], axis=1)
    proc.ingest(cid, samples, sample_rate_hz=sr)


class TestMultiSpectrumAlignment:
    """multi_spectrum_payload should expose stable alignment metadata."""

    def test_single_sensor_no_alignment_key(self) -> None:
        proc = _proc()
        _inject(proc, "c1", n=1024)
        proc.compute_metrics("c1")
        result = proc.multi_spectrum_payload(["c1"])
        assert "alignment" not in result

    def test_two_sensors_produces_alignment(self) -> None:
        proc = _proc()
        _inject(proc, "c1", n=1024)
        _inject(proc, "c2", n=1024)
        proc.compute_metrics("c1")
        proc.compute_metrics("c2")
        result = proc.multi_spectrum_payload(["c1", "c2"])
        assert "alignment" in result
        alignment = result["alignment"]
        assert "overlap_ratio" in alignment
        assert "aligned" in alignment
        assert isinstance(alignment["sensor_count"], int)
        assert alignment["sensor_count"] == 2

    def test_alignment_overlap_ratio_is_finite(self) -> None:
        proc = _proc()
        _inject(proc, "c1", n=1024)
        _inject(proc, "c2", n=1024)
        proc.compute_metrics("c1")
        proc.compute_metrics("c2")
        result = proc.multi_spectrum_payload(["c1", "c2"])
        assert math.isfinite(result["alignment"]["overlap_ratio"])
        assert isinstance(result["alignment"]["clock_synced"], bool)
