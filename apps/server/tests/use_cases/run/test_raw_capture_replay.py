from __future__ import annotations

import math
from dataclasses import replace

import numpy as np

from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.run_context_warning import WARNING_CODE_RAW_REPLAY_DROPPED_CHUNKS
from vibesensor.shared.types.raw_capture import (
    RawCaptureChunkIndex,
    RawCaptureLossStats,
    RawCaptureManifest,
    RawCaptureSensorClockSync,
    RawCaptureSensorData,
    RawCaptureSensorLossStats,
    RawCaptureSensorManifest,
    RawRunCapture,
)
from vibesensor.use_cases.run.post_analysis_input import build_post_analysis_input
from vibesensor.use_cases.run.post_analysis_loader import LoadedPostAnalysisRun


def _metadata(run_id: str):
    return run_metadata_from_mapping(
        {
            "run_id": run_id,
            "start_time_utc": "2025-01-01T00:00:00Z",
            "sensor_model": "fixture-sensor",
            "raw_sample_rate_hz": 800,
            "sample_rate_hz": 800,
            "feature_interval_s": 1.0,
            "fft_window_size_samples": 64,
            "accel_scale_g_per_lsb": 0.001,
            "language": "en",
        }
    )


def _raw_capture(run_id: str) -> RawRunCapture:
    sample_rate_hz = 800
    fft_n = 64
    time_axis = np.arange(fft_n, dtype=np.float64) / sample_rate_hz
    wave = np.round(1000.0 * np.sin(2.0 * math.pi * 50.0 * time_axis)).astype(np.int16)
    samples_i16 = np.column_stack(
        [
            wave,
            np.zeros(fft_n, dtype=np.int16),
            np.zeros(fft_n, dtype=np.int16),
        ]
    )
    sensor_manifest = RawCaptureSensorManifest(
        client_id="sensor-a",
        sample_rate_hz=sample_rate_hz,
        data_file="sensor-a.raw.i16le",
        index_file="sensor-a.index.jsonl",
        sample_count=fft_n,
        chunk_count=1,
        bytes_written=int(samples_i16.nbytes),
        first_t0_us=1,
        last_t0_us=1,
        clock_sync=RawCaptureSensorClockSync(
            clock_domain="server_monotonic",
            proof_state="verified",
            observed_monotonic_us=1_010_000,
            last_sync_monotonic_us=1_009_000,
            sync_offset_us=5_000,
            sync_rtt_us=4_000,
        ),
    )
    manifest = RawCaptureManifest(
        run_id=run_id,
        relative_dir=f"raw-runs/{run_id}",
        sensors=(sensor_manifest,),
        total_samples=fft_n,
        total_bytes=int(samples_i16.nbytes),
        created_at="2025-01-01T00:00:01Z",
        run_start_monotonic_us=1_000_000,
    )
    return RawRunCapture(
        manifest=manifest,
        sensors=(
            RawCaptureSensorData(
                manifest=sensor_manifest,
                samples_i16=samples_i16,
                chunks=(
                    RawCaptureChunkIndex(
                        sample_start=0,
                        sample_count=fft_n,
                        t0_us=1_000_000,
                        byte_offset=0,
                    ),
                ),
            ),
        ),
    )


def test_build_post_analysis_input_replays_raw_backed_strength_metrics() -> None:
    loaded = LoadedPostAnalysisRun(
        run_id="run-raw",
        metadata=_metadata("run-raw"),
        language="en",
        samples=sensor_frames_from_mappings(
            [
                {
                    "client_id": "sensor-a",
                    "t_s": 64 / 800,
                    "sample_rate_hz": 800,
                    "vibration_strength_db": 0.0,
                    "dominant_freq_hz": 0.0,
                }
            ]
        ),
        raw_capture=_raw_capture("run-raw"),
        total_summary_row_count=1,
        stride=1,
    )

    result = build_post_analysis_input(loaded)

    rebuilt = result.diagnostics_run.samples[0]
    assert result.raw_capture_available is True
    assert result.raw_backed_summary_row_count == 1
    assert rebuilt.vibration_strength_db is not None
    assert rebuilt.vibration_strength_db > 0.0
    assert rebuilt.dominant_freq_hz is not None
    assert 30.0 <= rebuilt.dominant_freq_hz <= 70.0
    assert rebuilt.top_peaks


def test_build_post_analysis_input_surfaces_persisted_dropped_chunk_counts() -> None:
    raw_capture = _raw_capture("run-drops")
    loss_stats = RawCaptureLossStats(
        udp_ingest_queue_drop_count=1,
        queue_overflow_chunk_count=2,
        invalid_chunk_count=1,
    )
    raw_capture = RawRunCapture(
        manifest=replace(
            raw_capture.manifest,
            sensor_losses=(RawCaptureSensorLossStats(client_id="sensor-a", losses=loss_stats),),
            losses=loss_stats,
        ),
        sensors=raw_capture.sensors,
    )
    loaded = LoadedPostAnalysisRun(
        run_id="run-drops",
        metadata=_metadata("run-drops"),
        language="en",
        samples=sensor_frames_from_mappings(
            [
                {
                    "client_id": "sensor-a",
                    "t_s": 64 / 800,
                    "sample_rate_hz": 800,
                    "vibration_strength_db": 0.0,
                    "dominant_freq_hz": 0.0,
                }
            ]
        ),
        raw_capture=raw_capture,
        total_summary_row_count=1,
        stride=1,
    )

    result = build_post_analysis_input(loaded)

    assert result.raw_backed_summary_row_count == 1
    assert result.raw_replay.dropped_chunk_count == 4
    assert result.raw_replay.udp_ingest_queue_drop_count == 1
    assert result.raw_replay.queue_overflow_chunk_count == 2
    assert result.raw_replay.invalid_chunk_count == 1
    assert result.raw_replay.write_error_chunk_count == 0
    assert result.raw_replay.replay_confidence == "partial"
    assert result.raw_replay.raw_capture_mode == "partial_raw_backed"
    assert WARNING_CODE_RAW_REPLAY_DROPPED_CHUNKS in [
        warning.code for warning in result.raw_replay.warnings
    ]


def test_build_post_analysis_input_falls_back_when_raw_capture_missing() -> None:
    loaded = LoadedPostAnalysisRun(
        run_id="run-summary",
        metadata=_metadata("run-summary"),
        language="en",
        samples=sensor_frames_from_mappings(
            [
                {
                    "client_id": "sensor-a",
                    "t_s": 64 / 800,
                    "sample_rate_hz": 800,
                    "vibration_strength_db": 12.0,
                    "dominant_freq_hz": 14.0,
                }
            ]
        ),
        raw_capture=None,
        total_summary_row_count=1,
        stride=1,
    )

    result = build_post_analysis_input(loaded)

    assert result.raw_capture_available is False
    assert result.raw_backed_summary_row_count == 0
    assert result.diagnostics_run.samples[0].vibration_strength_db == 12.0
