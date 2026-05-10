from __future__ import annotations

import math

import numpy as np

from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.types.raw_capture import (
    RawCaptureChunkIndex,
    RawCaptureManifest,
    RawCaptureSensorClockSync,
    RawCaptureSensorData,
    RawCaptureSensorManifest,
    RawRunCapture,
)
from vibesensor.use_cases.run import raw_capture_replay

_SAMPLE_RATE_HZ = 800
_FFT_N = 64
_RUN_START_MONOTONIC_US = 1_000_000


def _metadata(run_id: str):
    return run_metadata_from_mapping(
        {
            "run_id": run_id,
            "start_time_utc": "2025-01-01T00:00:00Z",
            "sensor_model": "fixture-sensor",
            "raw_sample_rate_hz": _SAMPLE_RATE_HZ,
            "sample_rate_hz": _SAMPLE_RATE_HZ,
            "feature_interval_s": 1.0,
            "fft_window_size_samples": _FFT_N,
            "accel_scale_g_per_lsb": 0.001,
            "language": "en",
        }
    )


def _wave(freq_hz: float, sample_count: int) -> np.ndarray:
    time_axis = np.arange(sample_count, dtype=np.float64) / float(_SAMPLE_RATE_HZ)
    wave = np.round(1000.0 * np.sin(2.0 * math.pi * freq_hz * time_axis)).astype(np.int16)
    return np.column_stack(
        [
            wave,
            np.zeros(sample_count, dtype=np.int16),
            np.zeros(sample_count, dtype=np.int16),
        ]
    )


def _analysis_window_end_us(*, raw_start_offset_us: int, sample_end: int) -> int:
    return int(
        raw_start_offset_us + (float(sample_end) / float(_SAMPLE_RATE_HZ) * 1_000_000.0),
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
    run_id: str,
    *,
    sensors: list[tuple[str, list[tuple[int, np.ndarray]]]],
) -> RawRunCapture:
    sensor_rows: list[RawCaptureSensorData] = []
    sensor_manifests: list[RawCaptureSensorManifest] = []
    total_samples = 0
    total_bytes = 0
    for client_id, chunks in sensors:
        sample_start = 0
        byte_offset = 0
        chunk_indexes: list[RawCaptureChunkIndex] = []
        sample_arrays: list[np.ndarray] = []
        for t0_us, samples in chunks:
            normalized = np.ascontiguousarray(samples, dtype=np.int16)
            sample_arrays.append(normalized)
            chunk_indexes.append(
                RawCaptureChunkIndex(
                    sample_start=sample_start,
                    sample_count=int(normalized.shape[0]),
                    t0_us=t0_us,
                    byte_offset=byte_offset,
                )
            )
            sample_start += int(normalized.shape[0])
            byte_offset += int(normalized.nbytes)
        samples_i16 = np.vstack(sample_arrays)
        manifest = RawCaptureSensorManifest(
            client_id=client_id,
            sample_rate_hz=_SAMPLE_RATE_HZ,
            data_file=f"{client_id}.raw.i16le",
            index_file=f"{client_id}.index.jsonl",
            sample_count=int(samples_i16.shape[0]),
            chunk_count=len(chunk_indexes),
            bytes_written=int(samples_i16.nbytes),
            first_t0_us=chunks[0][0],
            last_t0_us=chunks[-1][0],
            clock_sync=_verified_clock_sync(),
            declared_sample_rate_hz=_SAMPLE_RATE_HZ,
            sample_rate_proof_state="observed_consistent",
        )
        sensor_rows.append(
            RawCaptureSensorData(
                manifest=manifest,
                samples_i16=samples_i16,
                chunks=tuple(chunk_indexes),
            )
        )
        sensor_manifests.append(manifest)
        total_samples += manifest.sample_count
        total_bytes += manifest.bytes_written
    manifest = RawCaptureManifest(
        run_id=run_id,
        relative_dir=f"raw-runs/{run_id}",
        sensors=tuple(sensor_manifests),
        total_samples=total_samples,
        total_bytes=total_bytes,
        created_at="2025-01-01T00:00:01Z",
        run_start_monotonic_us=_RUN_START_MONOTONIC_US,
    )
    return RawRunCapture(manifest=manifest, sensors=tuple(sensor_rows))


def test_raw_replay_phase_builds_timelines_and_windows_per_client() -> None:
    sensor_a_offset_us = 100_000
    sensor_b_offset_us = 140_000
    raw_capture = _raw_capture(
        "run-phase-windows",
        sensors=[
            (
                "sensor-a",
                [(_RUN_START_MONOTONIC_US + sensor_a_offset_us, _wave(28.0, _FFT_N))],
            ),
            (
                "sensor-b",
                [(_RUN_START_MONOTONIC_US + sensor_b_offset_us, _wave(52.0, _FFT_N))],
            ),
        ],
    )
    samples = sensor_frames_from_mappings(
        [
            {
                "client_id": "sensor-a",
                "analysis_window_end_us": _analysis_window_end_us(
                    raw_start_offset_us=sensor_a_offset_us,
                    sample_end=_FFT_N,
                ),
                "sample_rate_hz": _SAMPLE_RATE_HZ,
                "vibration_strength_db": 0.0,
                "dominant_freq_hz": 0.0,
            },
            {
                "client_id": "sensor-b",
                "analysis_window_end_us": _analysis_window_end_us(
                    raw_start_offset_us=sensor_b_offset_us,
                    sample_end=_FFT_N,
                ),
                "sample_rate_hz": _SAMPLE_RATE_HZ,
                "vibration_strength_db": 0.0,
                "dominant_freq_hz": 0.0,
            },
        ]
    )

    context = raw_capture_replay._build_replay_context(
        metadata=_metadata("run-phase-windows"),
        raw_capture=raw_capture,
        fft_n=_FFT_N,
    )
    windows = raw_capture_replay._build_replay_windows(
        samples=samples,
        raw_capture=raw_capture,
        context=context,
    )

    assert set(context.timelines) == {"sensor-a", "sensor-b"}
    assert windows.raw_backed_count == 2
    assert windows.complete_window_count == 2
    assert windows.partial_window_count == 0
    assert windows.missing_window_count == 0
    assert [coverage.client_id for coverage in windows.coverages] == ["sensor-a", "sensor-b"]
    assert {sample.client_id for sample in windows.samples} == {"sensor-a", "sensor-b"}
    assert all(sample.dominant_freq_hz is not None for sample in windows.samples)


def test_raw_replay_phase_marks_unavailable_capture_windows_missing() -> None:
    samples = sensor_frames_from_mappings(
        [
            {
                "client_id": "sensor-a",
                "t_s": 0.2,
                "sample_rate_hz": _SAMPLE_RATE_HZ,
                "vibration_strength_db": 3.0,
                "dominant_freq_hz": 4.0,
            },
            {
                "client_id": "sensor-b",
                "t_s": 0.3,
                "sample_rate_hz": _SAMPLE_RATE_HZ,
                "vibration_strength_db": 5.0,
                "dominant_freq_hz": 6.0,
            },
        ]
    )

    result = raw_capture_replay._build_raw_capture_unavailable_replay_result(samples)

    assert result.samples == samples
    assert result.summary.raw_capture_available is False
    assert result.summary.replay_confidence == "unavailable"
    assert result.summary.raw_capture_mode == "summary_only"
    assert result.summary.missing_window_count == 2
    assert [coverage.reason for coverage in result.window_coverages] == [
        "raw_capture_unavailable",
        "raw_capture_unavailable",
    ]
