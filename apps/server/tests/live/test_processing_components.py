"""Cover metrics computation from snapshots and FFT-parameter caching."""

from __future__ import annotations

import numpy as np

from vibesensor.dsp.fft_analysis import axis_peaks_from_spectrum
from vibesensor.live.compute import SignalMetricsComputer
from vibesensor.live.models import MetricsSnapshot, ProcessorConfig


def _config(**overrides: object) -> ProcessorConfig:
    base = {
        "sample_rate_hz": 200,
        "waveform_seconds": 2,
        "waveform_display_hz": 50,
        "fft_n": 128,
        "spectrum_min_hz": 0.0,
        "spectrum_max_hz": 100.0,
        "accel_scale_g_per_lsb": None,
    }
    base.update(overrides)
    return ProcessorConfig(**base)


def test_metrics_computer_operates_on_snapshot_without_shared_state() -> None:
    config = _config(sample_rate_hz=400, fft_n=256, spectrum_max_hz=150.0)
    computer = SignalMetricsComputer(config)
    t = np.arange(config.fft_n, dtype=np.float32) / np.float32(config.sample_rate_hz)
    tone = (0.05 * np.sin(2.0 * np.pi * 20.0 * t)).astype(np.float32)
    block = np.stack([tone, np.zeros_like(tone), np.zeros_like(tone)], axis=0)
    snapshot = MetricsSnapshot(
        client_id="client-2",
        sample_rate_hz=config.sample_rate_hz,
        ingest_generation=7,
        fft_block=block.copy(),
    )

    result = computer.compute(snapshot)

    assert result.client_id == "client-2"
    assert result.ingest_generation == 7
    assert any(
        abs(float(peak["hz"]) - 20.0) < 1.0
        for peak in axis_peaks_from_spectrum(
            freq_slice=result.metrics["x"]["freq"], amp_slice=result.metrics["x"]["amp"]
        )
    )
    assert any(abs(float(peak["hz"]) - 20.0) < 1.0 for peak in result.metrics["combined"]["peaks"])


def test_fft_cache_uses_lru_eviction(monkeypatch) -> None:
    monkeypatch.setattr("vibesensor.dsp.fft_analysis._FFT_CACHE_MAXSIZE", 2)
    computer = SignalMetricsComputer(_config(fft_n=8, sample_rate_hz=200, spectrum_max_hz=90.0))

    computer.strength_range_mask(200)
    computer.strength_range_mask(300)
    computer.strength_range_mask(200)
    computer.strength_range_mask(400)

    assert list(computer.fft_cache) == [200, 400]
