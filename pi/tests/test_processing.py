from __future__ import annotations

from math import pi, sqrt

import numpy as np

from vibesensor.processing import SignalProcessor


def test_processing_scales_to_g_detrends_dc_and_tracks_peak() -> None:
    sample_rate_hz = 800
    fft_n = 2048
    processor = SignalProcessor(
        sample_rate_hz=sample_rate_hz,
        waveform_seconds=8,
        waveform_display_hz=100,
        fft_n=fft_n,
        spectrum_max_hz=200,
        accel_scale_g_per_lsb=1.0 / 256.0,
    )

    t = np.arange(fft_n, dtype=np.float64) / sample_rate_hz
    x_g = 1.0 + (0.05 * np.sin(2.0 * pi * 20.0 * t))
    y_g = np.zeros_like(x_g)
    z_g = np.zeros_like(x_g)
    raw_lsb = np.stack([x_g * 256.0, y_g * 256.0, z_g * 256.0], axis=1).astype(np.int16)
    processor.ingest("c1", raw_lsb, sample_rate_hz=sample_rate_hz)

    metrics = processor.compute_metrics("c1", sample_rate_hz=sample_rate_hz)
    expected_rms = 0.05 / sqrt(2.0)
    assert abs(float(metrics["x"]["rms"]) - expected_rms) < 0.006

    combined = metrics["combined"]
    peaks = combined["peaks"]
    assert peaks
    assert any(abs(float(peak["hz"]) - 20.0) < 1.0 for peak in peaks)


def test_processing_window_seconds_uses_client_sample_rate() -> None:
    sample_rate_hz = 400
    processor = SignalProcessor(
        sample_rate_hz=800,
        waveform_seconds=8,
        waveform_display_hz=100,
        fft_n=1024,
        spectrum_max_hz=200,
        accel_scale_g_per_lsb=None,
    )

    total_samples = 5000
    t = np.arange(total_samples, dtype=np.float64) / sample_rate_hz
    x = np.zeros(total_samples, dtype=np.float32)
    x[:1800] = (0.8 * np.sin(2.0 * pi * 6.0 * t[:1800])).astype(np.float32)
    x[1800:] = (0.1 * np.sin(2.0 * pi * 6.0 * t[1800:])).astype(np.float32)
    samples = np.stack([x, np.zeros_like(x), np.zeros_like(x)], axis=1)
    processor.ingest("c1", samples, sample_rate_hz=sample_rate_hz)

    metrics = processor.compute_metrics("c1", sample_rate_hz=sample_rate_hz)
    # If more than the last 8 seconds were used, RMS would be much higher.
    assert float(metrics["x"]["rms"]) < 0.12
