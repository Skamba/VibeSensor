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


def test_ingest_not_blocked_during_compute() -> None:
    """Regression: ingest must stay responsive while compute_metrics runs in a thread.

    Before the snapshot-based refactor, compute_metrics held the processor
    lock for the entire FFT computation, blocking ingest on the event loop.
    """
    sample_rate_hz = 800
    fft_n = 2048
    processor = SignalProcessor(
        sample_rate_hz=sample_rate_hz,
        waveform_seconds=8,
        waveform_display_hz=100,
        fft_n=fft_n,
        spectrum_max_hz=200,
    )
    # Seed buffer with enough data for FFT
    seed = np.random.default_rng(42).standard_normal((fft_n * 2, 3)).astype(np.float32)
    processor.ingest("c1", seed, sample_rate_hz=sample_rate_hz)

    compute_started = Event()
    compute_done = Event()
    ingest_latencies: list[float] = []

    def _compute_loop() -> None:
        compute_started.set()
        for _ in range(10):
            processor.compute_metrics("c1", sample_rate_hz=sample_rate_hz)
            # Bump ingest generation so compute doesn't fast-path skip
            processor.ingest(
                "c1",
                np.random.default_rng(0).standard_normal((100, 3)).astype(np.float32),
                sample_rate_hz=sample_rate_hz,
            )
        compute_done.set()

    worker = Thread(target=_compute_loop)
    worker.start()
    compute_started.wait(timeout=2.0)

    # Repeatedly ingest while compute runs and measure latency
    chunk = np.zeros((50, 3), dtype=np.float32)
    while not compute_done.is_set():
        t0 = time.monotonic()
        processor.ingest("c2", chunk, sample_rate_hz=sample_rate_hz)
        ingest_latencies.append(time.monotonic() - t0)

    worker.join(timeout=5.0)
    assert compute_done.is_set()
    assert ingest_latencies, "Should have measured at least some ingest calls"
    max_latency_ms = max(ingest_latencies) * 1000
    # With snapshot-based compute, ingest should never be blocked for more
    # than a few milliseconds (lock is held only briefly for snapshot/store).
    assert max_latency_ms < 50, (
        f"Ingest latency spike {max_latency_ms:.1f}ms during compute; "
        "expected < 50ms with snapshot-based locking"
    )


def test_intake_stats_tracks_samples_and_compute() -> None:
    processor = SignalProcessor(
        sample_rate_hz=800,
        waveform_seconds=8,
        waveform_display_hz=100,
        fft_n=1024,
        spectrum_max_hz=200,
    )
    stats_before = processor.intake_stats()
    assert stats_before["total_ingested_samples"] == 0
    assert stats_before["total_compute_calls"] == 0

    samples = np.zeros((100, 3), dtype=np.float32)
    processor.ingest("c1", samples, sample_rate_hz=800)

    stats_after_ingest = processor.intake_stats()
    assert stats_after_ingest["total_ingested_samples"] == 100

    # Seed enough data for FFT
    big_chunk = np.zeros((1024, 3), dtype=np.float32)
    processor.ingest("c1", big_chunk, sample_rate_hz=800)
    processor.compute_metrics("c1", sample_rate_hz=800)

    stats_after_compute = processor.intake_stats()
    assert stats_after_compute["total_compute_calls"] == 1
    assert stats_after_compute["last_compute_duration_s"] > 0


def test_spectrum_min_hz_excludes_low_frequency_bins() -> None:
    """spectrum_min_hz should prevent sub-cutoff bins from appearing in peaks."""
    sample_rate_hz = 800
    fft_n = 2048
    min_hz = 5.0
    processor = SignalProcessor(
        sample_rate_hz=sample_rate_hz,
        waveform_seconds=8,
        waveform_display_hz=100,
        fft_n=fft_n,
        spectrum_min_hz=min_hz,
        spectrum_max_hz=200,
    )

    # Inject a strong 2 Hz signal (below spectrum_min_hz) + a 20 Hz signal.
    t = np.arange(fft_n, dtype=np.float64) / sample_rate_hz
    x = (0.1 * np.sin(2.0 * pi * 2.0 * t) + 0.05 * np.sin(2.0 * pi * 20.0 * t)).astype(np.float32)
    samples = np.stack([x, np.zeros_like(x), np.zeros_like(x)], axis=1)
    processor.ingest("c1", samples, sample_rate_hz=sample_rate_hz)

    metrics = processor.compute_metrics("c1", sample_rate_hz=sample_rate_hz)
    combined_peaks = metrics.get("combined", {}).get("peaks", [])
    # No peak should be below spectrum_min_hz.
    for peak in combined_peaks:
        assert float(peak["hz"]) >= min_hz, f"Peak at {peak['hz']} Hz is below {min_hz} Hz cutoff"
    # The 20 Hz peak should still be present.
    assert any(abs(float(p["hz"]) - 20.0) < 1.0 for p in combined_peaks)


def test_spectrum_min_hz_zero_allows_all_frequencies() -> None:
    """spectrum_min_hz=0 should behave like no cutoff (existing default)."""
    sample_rate_hz = 400
    fft_n = 1024
    processor = SignalProcessor(
        sample_rate_hz=sample_rate_hz,
        waveform_seconds=8,
        waveform_display_hz=100,
        fft_n=fft_n,
        spectrum_min_hz=0.0,
        spectrum_max_hz=200,
    )

    t = np.arange(fft_n, dtype=np.float64) / sample_rate_hz
    x = (0.1 * np.sin(2.0 * pi * 2.0 * t)).astype(np.float32)
    samples = np.stack([x, np.zeros_like(x), np.zeros_like(x)], axis=1)
    processor.ingest("c1", samples, sample_rate_hz=sample_rate_hz)

    metrics = processor.compute_metrics("c1", sample_rate_hz=sample_rate_hz)
    combined_peaks = metrics.get("combined", {}).get("peaks", [])
    # With min_hz=0, the 2 Hz peak should appear.
    assert any(abs(float(p["hz"]) - 2.0) < 1.0 for p in combined_peaks)
