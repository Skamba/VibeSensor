from __future__ import annotations

import time
from math import pi, sqrt
from threading import Event, Thread

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


def test_clients_with_recent_data_filters_stale() -> None:
    processor = SignalProcessor(
        sample_rate_hz=800,
        waveform_seconds=8,
        waveform_display_hz=100,
        fft_n=1024,
        spectrum_max_hz=200,
    )

    samples = np.zeros((10, 3), dtype=np.float32)
    processor.ingest("c1", samples, sample_rate_hz=800)
    processor.ingest("c2", samples, sample_rate_hz=800)

    # Make c2's last ingest look old by patching its timestamp
    processor._buffers["c2"].last_ingest_mono_s = time.monotonic() - 10.0

    result = processor.clients_with_recent_data(["c1", "c2", "c3"], max_age_s=3.0)
    assert result == ["c1"]


def test_ingest_waits_while_processor_lock_is_held() -> None:
    processor = SignalProcessor(
        sample_rate_hz=800,
        waveform_seconds=8,
        waveform_display_hz=100,
        fft_n=1024,
        spectrum_max_hz=200,
    )
    samples = np.zeros((10, 3), dtype=np.float32)
    done = Event()

    def _ingest() -> None:
        processor.ingest("c-lock", samples, sample_rate_hz=800)
        done.set()

    processor._lock.acquire()
    worker = Thread(target=_ingest)
    worker.start()
    try:
        assert not done.wait(timeout=0.05)
    finally:
        processor._lock.release()
    worker.join(timeout=1.0)
    assert done.is_set()
