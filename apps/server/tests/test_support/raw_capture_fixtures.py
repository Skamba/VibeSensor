"""Building blocks for post-analysis inputs: run metadata, raw sine samples, a verified clock."""

from __future__ import annotations

import numpy as np

from vibesensor.recording.raw_capture import RawCaptureSensorClockSync
from vibesensor.recording.run_metadata import run_metadata_from_mapping
from vibesensor.recording.run_schema import RunMetadata


def post_analysis_metadata(
    run_id: str,
    *,
    sample_rate_hz: int = 800,
    fft_n: int = 64,
    feature_interval_s: float | None = 1.0,
    language: str = "en",
    **extra: object,
) -> RunMetadata:
    """Metadata of a recorded run as post-analysis reads it."""
    payload: dict[str, object] = {
        "run_id": run_id,
        "start_time_utc": "2025-01-01T00:00:00Z",
        "sensor_model": "fixture-sensor",
        "raw_sample_rate_hz": sample_rate_hz,
        "sample_rate_hz": sample_rate_hz,
        "fft_window_size_samples": fft_n,
        "accel_scale_g_per_lsb": 0.001,
        "language": language,
        **extra,
    }
    if feature_interval_s is not None:
        payload["feature_interval_s"] = feature_interval_s
    return run_metadata_from_mapping(payload)


def sine_xyz_i16(freq_hz: float, sample_count: int, *, sample_rate_hz: int = 800) -> np.ndarray:
    """Raw int16 x/y/z samples: a sine on x, silence on y and z."""
    time_axis = np.arange(sample_count, dtype=np.float64) / float(sample_rate_hz)
    wave = np.round(1000.0 * np.sin(2.0 * np.pi * freq_hz * time_axis)).astype(np.int16)
    silence = np.zeros(sample_count, dtype=np.int16)
    return np.column_stack([wave, silence, silence])


def verified_clock_sync() -> RawCaptureSensorClockSync:
    """A sensor clock whose server-monotonic offset was verified shortly before recording."""
    return RawCaptureSensorClockSync(
        clock_domain="server_monotonic",
        proof_state="verified",
        observed_monotonic_us=1_010_000,
        last_sync_monotonic_us=1_009_000,
        sync_offset_us=5_000,
        sync_rtt_us=4_000,
        max_sync_age_us=15_000_000,
        max_sync_rtt_us=50_000,
    )
