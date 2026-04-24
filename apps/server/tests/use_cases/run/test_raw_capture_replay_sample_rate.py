from __future__ import annotations

import math

import numpy as np
import pytest

from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.run_context_warning import (
    WARNING_CODE_RAW_REPLAY_COVERAGE_INCOMPLETE,
    WARNING_CODE_RAW_REPLAY_TIMING_FALLBACK,
)
from vibesensor.shared.types.raw_capture import (
    RawCaptureChunkIndex,
    RawCaptureManifest,
    RawCaptureSensorClockSync,
    RawCaptureSensorData,
    RawCaptureSensorManifest,
    RawRunCapture,
)
from vibesensor.use_cases.run import raw_capture_replay
from vibesensor.use_cases.run.post_analysis_input import build_post_analysis_input
from vibesensor.use_cases.run.post_analysis_loader import LoadedPostAnalysisRun

_DECLARED_SAMPLE_RATE_HZ = 800
_FFT_N = 64
_RUN_START_MONOTONIC_US = 1_000_000


def _metadata(run_id: str):
    return run_metadata_from_mapping(
        {
            "run_id": run_id,
            "start_time_utc": "2025-01-01T00:00:00Z",
            "sensor_model": "fixture-sensor",
            "raw_sample_rate_hz": _DECLARED_SAMPLE_RATE_HZ,
            "sample_rate_hz": _DECLARED_SAMPLE_RATE_HZ,
            "feature_interval_s": 1.0,
            "fft_window_size_samples": _FFT_N,
            "accel_scale_g_per_lsb": 0.001,
            "language": "en",
        }
    )


def _wave(freq_hz: float, sample_count: int, *, sample_rate_hz: int) -> np.ndarray:
    time_axis = np.arange(sample_count, dtype=np.float64) / float(sample_rate_hz)
    wave = np.round(1000.0 * np.sin(2.0 * math.pi * freq_hz * time_axis)).astype(np.int16)
    return np.column_stack(
        [
            wave,
            np.zeros(sample_count, dtype=np.int16),
            np.zeros(sample_count, dtype=np.int16),
        ]
    )


def _verified_clock_sync() -> RawCaptureSensorClockSync:
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


def _raw_capture(
    *,
    run_id: str,
    sample_rate_hz: int,
    declared_sample_rate_hz: int,
    sample_rate_proof_state: str,
    raw_start_offset_us: int,
) -> RawRunCapture:
    samples_i16 = np.vstack(
        [
            _wave(36.0, _FFT_N, sample_rate_hz=sample_rate_hz),
            _wave(80.0, 96, sample_rate_hz=sample_rate_hz),
        ]
    )
    manifest = RawCaptureSensorManifest(
        client_id="sensor-a",
        sample_rate_hz=sample_rate_hz,
        data_file="sensor-a.raw.i16le",
        index_file="sensor-a.index.jsonl",
        sample_count=int(samples_i16.shape[0]),
        chunk_count=1,
        bytes_written=int(samples_i16.nbytes),
        first_t0_us=_RUN_START_MONOTONIC_US + raw_start_offset_us,
        last_t0_us=_RUN_START_MONOTONIC_US + raw_start_offset_us,
        clock_sync=_verified_clock_sync(),
        declared_sample_rate_hz=declared_sample_rate_hz,
        sample_rate_proof_state=sample_rate_proof_state,
    )
    return RawRunCapture(
        manifest=RawCaptureManifest(
            run_id=run_id,
            relative_dir=f"raw-runs/{run_id}",
            sensors=(manifest,),
            total_samples=int(samples_i16.shape[0]),
            total_bytes=int(samples_i16.nbytes),
            created_at="2025-01-01T00:00:01Z",
            run_start_monotonic_us=_RUN_START_MONOTONIC_US,
        ),
        sensors=(
            RawCaptureSensorData(
                manifest=manifest,
                samples_i16=samples_i16,
                chunks=(
                    RawCaptureChunkIndex(
                        sample_start=0,
                        sample_count=int(samples_i16.shape[0]),
                        t0_us=_RUN_START_MONOTONIC_US + raw_start_offset_us,
                        byte_offset=0,
                    ),
                ),
            ),
        ),
    )


def test_build_post_analysis_input_uses_corrected_observed_sample_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_sample_rate_hz = 780
    raw_start_offset_us = 100_000
    loaded = LoadedPostAnalysisRun(
        run_id="run-corrected-rate",
        metadata=_metadata("run-corrected-rate"),
        language="en",
        samples=sensor_frames_from_mappings(
            [
                {
                    "client_id": "sensor-a",
                    "t_s": 0.0,
                    "analysis_window_end_us": int(
                        raw_start_offset_us
                        + (float(_FFT_N) / float(observed_sample_rate_hz) * 1_000_000.0)
                    ),
                    "sample_rate_hz": _DECLARED_SAMPLE_RATE_HZ,
                    "vibration_strength_db": 0.0,
                    "dominant_freq_hz": 0.0,
                }
            ]
        ),
        raw_capture=_raw_capture(
            run_id="run-corrected-rate",
            sample_rate_hz=observed_sample_rate_hz,
            declared_sample_rate_hz=_DECLARED_SAMPLE_RATE_HZ,
            sample_rate_proof_state="observed_consistent",
            raw_start_offset_us=raw_start_offset_us,
        ),
        total_sample_count=1,
        stride=1,
    )
    calls: list[int] = []
    original_compute = raw_capture_replay.SpectralAnalysisComputer.compute_fft_spectrum

    def _counting_compute(self, fft_block, sample_rate_hz, **kwargs):
        calls.append(sample_rate_hz)
        return original_compute(self, fft_block, sample_rate_hz, **kwargs)

    monkeypatch.setattr(
        raw_capture_replay.SpectralAnalysisComputer,
        "compute_fft_spectrum",
        _counting_compute,
    )

    result = build_post_analysis_input(loaded)

    assert result.raw_backed_sample_count == 1
    assert result.raw_replay.sample_rate_mismatch_count == 1
    assert result.raw_replay.replay_confidence == "partial"
    assert calls == [observed_sample_rate_hz]
    assert [warning.code for warning in result.raw_replay.warnings] == [
        WARNING_CODE_RAW_REPLAY_COVERAGE_INCOMPLETE
    ]
    assert result.raw_replay_window_coverages[0].reason == "sample_rate_mismatch"


def test_build_post_analysis_input_warns_for_unverified_sample_rate_manifest() -> None:
    raw_start_offset_us = 100_000
    loaded = LoadedPostAnalysisRun(
        run_id="run-unverified-rate",
        metadata=_metadata("run-unverified-rate"),
        language="en",
        samples=sensor_frames_from_mappings(
            [
                {
                    "client_id": "sensor-a",
                    "t_s": (
                        float(raw_start_offset_us)
                        + (float(_FFT_N) / float(_DECLARED_SAMPLE_RATE_HZ) * 1_000_000.0)
                    )
                    / 1_000_000.0,
                    "sample_rate_hz": _DECLARED_SAMPLE_RATE_HZ,
                    "vibration_strength_db": 0.0,
                    "dominant_freq_hz": 0.0,
                }
            ]
        ),
        raw_capture=_raw_capture(
            run_id="run-unverified-rate",
            sample_rate_hz=_DECLARED_SAMPLE_RATE_HZ,
            declared_sample_rate_hz=_DECLARED_SAMPLE_RATE_HZ,
            sample_rate_proof_state="declared_only",
            raw_start_offset_us=raw_start_offset_us,
        ),
        total_sample_count=1,
        stride=1,
    )

    result = build_post_analysis_input(loaded)

    assert result.raw_backed_sample_count == 1
    assert result.raw_replay.sample_rate_unverified_sensor_count == 1
    assert result.raw_replay.replay_confidence == "partial"
    assert [warning.code for warning in result.raw_replay.warnings] == [
        WARNING_CODE_RAW_REPLAY_TIMING_FALLBACK,
        WARNING_CODE_RAW_REPLAY_COVERAGE_INCOMPLETE,
    ]
