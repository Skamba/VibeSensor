"""Raw-capture replay for post-analysis: sample-rate proof, timing gaps, legacy captures, loss.

Windows the simulator benchmark cannot produce: a sensor running at a corrected
observed rate, chunk gaps, captures without a timing anchor, FFT windows without
valid bins and a fatal loss policy."""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest
from test_support.raw_capture_assertions import warning_codes
from test_support.raw_capture_fixtures import (
    post_analysis_metadata,
    sine_xyz_i16,
    verified_clock_sync,
)

from vibesensor.analysis import raw_capture_replay
from vibesensor.analysis.post_analysis_input import build_post_analysis_input
from vibesensor.analysis.post_analysis_loader import LoadedPostAnalysisRun
from vibesensor.recording.raw_capture import (
    RawCaptureChunkIndex,
    RawCaptureChunkTable,
    RawCaptureLossStats,
    RawCaptureManifest,
    RawCaptureSensorClockSync,
    RawCaptureSensorData,
    RawCaptureSensorLossStats,
    RawCaptureSensorManifest,
    RawRunCapture,
)
from vibesensor.recording.sensor_frame_mapping import sensor_frames_from_mappings
from vibesensor.summary.run_context_warning import (
    WARNING_CODE_RAW_CAPTURE_LOSS_POLICY,
    WARNING_CODE_RAW_REPLAY_COVERAGE_INCOMPLETE,
    WARNING_CODE_RAW_REPLAY_FFT_UNUSABLE,
    WARNING_CODE_RAW_REPLAY_LEGACY_FALLBACK,
    WARNING_CODE_RAW_REPLAY_TIMING_FALLBACK,
)

_SAMPLE_RATE_HZ = 800
_FFT_N = 64
_RUN_START_MONOTONIC_US = 1_000_000


def _rate_capture(
    *,
    run_id: str,
    sample_rate_hz: int,
    declared_sample_rate_hz: int,
    sample_rate_proof_state: str,
    raw_start_offset_us: int,
) -> RawRunCapture:
    samples_i16 = np.vstack(
        [
            sine_xyz_i16(36.0, _FFT_N, sample_rate_hz=sample_rate_hz),
            sine_xyz_i16(80.0, 96, sample_rate_hz=sample_rate_hz),
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
        clock_sync=verified_clock_sync(),
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
                chunks=RawCaptureChunkTable.from_rows(
                    [
                        RawCaptureChunkIndex(
                            sample_start=0,
                            sample_count=int(samples_i16.shape[0]),
                            t0_us=_RUN_START_MONOTONIC_US + raw_start_offset_us,
                            byte_offset=0,
                        )
                    ]
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
        metadata=post_analysis_metadata("run-corrected-rate"),
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
                    "sample_rate_hz": _SAMPLE_RATE_HZ,
                    "vibration_strength_db": 0.0,
                    "dominant_freq_hz": 0.0,
                }
            ]
        ),
        raw_capture=_rate_capture(
            run_id="run-corrected-rate",
            sample_rate_hz=observed_sample_rate_hz,
            declared_sample_rate_hz=_SAMPLE_RATE_HZ,
            sample_rate_proof_state="observed_consistent",
            raw_start_offset_us=raw_start_offset_us,
        ),
        total_summary_row_count=1,
        stride=1,
    )
    calls: list[int] = []
    original_compute = raw_capture_replay.SpectralAnalysisComputer.combined_spectrum

    def _counting_compute(self, fft_block, sample_rate_hz, **kwargs):
        calls.append(sample_rate_hz)
        return original_compute(self, fft_block, sample_rate_hz, **kwargs)

    monkeypatch.setattr(
        raw_capture_replay.SpectralAnalysisComputer,
        "combined_spectrum",
        _counting_compute,
    )

    result = build_post_analysis_input(loaded)

    assert result.raw_backed_summary_row_count == 1
    assert result.raw_replay.sample_rate_mismatch_count == 1
    assert result.raw_replay.replay_confidence == "partial"
    assert calls == [observed_sample_rate_hz]
    assert [warning.code for warning in result.raw_replay.warnings] == [
        WARNING_CODE_RAW_REPLAY_COVERAGE_INCOMPLETE
    ]
    assert result.raw_replay_window_coverages[0].reason == "sample_rate_mismatch"


def _sample_t_s(*, raw_start_offset_us: int, sample_end: int) -> float:
    return (
        float(raw_start_offset_us) + (float(sample_end) / float(_SAMPLE_RATE_HZ) * 1_000_000.0)
    ) / 1_000_000.0


def _timing_capture(
    run_id: str,
    *,
    sensors: list[tuple[str, list[tuple[int, np.ndarray]]]],
    run_start_monotonic_us: int | None = _RUN_START_MONOTONIC_US,
    clock_sync_by_sensor: dict[str, RawCaptureSensorClockSync | None] | None = None,
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
        samples_i16 = (
            np.vstack(sample_arrays) if sample_arrays else np.empty((0, 3), dtype=np.int16)
        )
        manifest = RawCaptureSensorManifest(
            client_id=client_id,
            sample_rate_hz=_SAMPLE_RATE_HZ,
            data_file=f"{client_id}.raw.i16le",
            index_file=f"{client_id}.index.jsonl",
            sample_count=int(samples_i16.shape[0]),
            chunk_count=len(chunk_indexes),
            bytes_written=int(samples_i16.nbytes),
            first_t0_us=chunks[0][0] if chunks else None,
            last_t0_us=chunks[-1][0] if chunks else None,
            clock_sync=(verified_clock_sync() if run_start_monotonic_us is not None else None)
            if clock_sync_by_sensor is None
            else clock_sync_by_sensor.get(client_id),
            declared_sample_rate_hz=_SAMPLE_RATE_HZ,
            sample_rate_proof_state="observed_consistent",
        )
        sensor_rows.append(
            RawCaptureSensorData(
                manifest=manifest,
                samples_i16=samples_i16,
                chunks=RawCaptureChunkTable.from_rows(chunk_indexes),
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
        run_start_monotonic_us=run_start_monotonic_us,
    )
    return RawRunCapture(manifest=manifest, sensors=tuple(sensor_rows))


def test_build_post_analysis_input_marks_gap_windows_partial_and_falls_back() -> None:
    raw_start_offset_us = 100_000
    first_chunk = sine_xyz_i16(34.0, _FFT_N, sample_rate_hz=_SAMPLE_RATE_HZ)
    second_chunk = sine_xyz_i16(74.0, _FFT_N, sample_rate_hz=_SAMPLE_RATE_HZ)
    raw_capture = _timing_capture(
        "run-gap",
        sensors=[
            (
                "sensor-a",
                [
                    (_RUN_START_MONOTONIC_US + raw_start_offset_us, first_chunk),
                    (_RUN_START_MONOTONIC_US + 220_000, second_chunk),
                ],
            )
        ],
    )
    loaded = LoadedPostAnalysisRun(
        run_id="run-gap",
        metadata=post_analysis_metadata("run-gap"),
        language="en",
        samples=sensor_frames_from_mappings(
            [
                {
                    "client_id": "sensor-a",
                    "t_s": _sample_t_s(raw_start_offset_us=raw_start_offset_us, sample_end=_FFT_N),
                    "sample_rate_hz": _SAMPLE_RATE_HZ,
                    "vibration_strength_db": 0.0,
                    "dominant_freq_hz": 0.0,
                },
                {
                    "client_id": "sensor-a",
                    "t_s": 0.24,
                    "sample_rate_hz": _SAMPLE_RATE_HZ,
                    "vibration_strength_db": 12.0,
                    "dominant_freq_hz": 14.0,
                },
            ]
        ),
        raw_capture=raw_capture,
        total_summary_row_count=2,
        stride=1,
    )

    result = build_post_analysis_input(loaded)

    assert result.raw_backed_summary_row_count == 1
    assert result.raw_replay.raw_capture_mode == "partial_raw_backed"
    assert result.raw_replay.partial_window_count == 1
    assert result.raw_replay.gap_count == 1
    assert warning_codes(result.raw_replay.warnings) == [
        WARNING_CODE_RAW_REPLAY_TIMING_FALLBACK,
        WARNING_CODE_RAW_REPLAY_COVERAGE_INCOMPLETE,
    ]
    assert [coverage.coverage_state for coverage in result.raw_replay_window_coverages] == [
        "complete",
        "partial",
    ]
    assert result.samples[1].vibration_strength_db == 12.0
    assert result.samples[1].dominant_freq_hz == 14.0


def test_build_post_analysis_input_falls_back_for_legacy_raw_capture_without_anchor() -> None:
    raw_start_offset_us = 100_000
    raw_capture = _timing_capture(
        "run-legacy",
        sensors=[
            (
                "sensor-a",
                [
                    (
                        _RUN_START_MONOTONIC_US + raw_start_offset_us,
                        np.vstack(
                            [
                                sine_xyz_i16(36.0, _FFT_N, sample_rate_hz=_SAMPLE_RATE_HZ),
                                sine_xyz_i16(80.0, 96, sample_rate_hz=_SAMPLE_RATE_HZ),
                            ]
                        ),
                    )
                ],
            )
        ],
        run_start_monotonic_us=None,
    )
    loaded = LoadedPostAnalysisRun(
        run_id="run-legacy",
        metadata=post_analysis_metadata("run-legacy"),
        language="en",
        samples=sensor_frames_from_mappings(
            [
                {
                    "client_id": "sensor-a",
                    "t_s": _sample_t_s(raw_start_offset_us=raw_start_offset_us, sample_end=_FFT_N),
                    "sample_rate_hz": _SAMPLE_RATE_HZ,
                    "vibration_strength_db": 11.0,
                    "dominant_freq_hz": 13.0,
                }
            ]
        ),
        raw_capture=raw_capture,
        total_summary_row_count=1,
        stride=1,
    )

    result = build_post_analysis_input(loaded)

    assert result.raw_backed_summary_row_count == 0
    assert result.raw_replay.raw_capture_mode == "summary_only"
    assert result.raw_replay.replay_confidence == "fallback"
    assert result.raw_replay.unanchored_sensor_count == 1
    assert warning_codes(result.raw_replay.warnings) == [WARNING_CODE_RAW_REPLAY_LEGACY_FALLBACK]
    assert result.samples[0].vibration_strength_db == 11.0
    assert result.samples[0].dominant_freq_hz == 13.0


def _outcome_capture(
    run_id: str, *, sample_rate_hz: int = 800, wave_hz: float = 50.0
) -> RawRunCapture:
    fft_n = 64
    time_axis = np.arange(fft_n, dtype=np.float64) / sample_rate_hz
    wave = np.round(1000.0 * np.sin(2.0 * math.pi * wave_hz * time_axis)).astype(np.int16)
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
                chunks=RawCaptureChunkTable.from_rows(
                    [
                        RawCaptureChunkIndex(
                            sample_start=0,
                            sample_count=fft_n,
                            t0_us=1_000_000,
                            byte_offset=0,
                        )
                    ]
                ),
            ),
        ),
    )


def test_build_post_analysis_input_marks_no_valid_bin_fft_windows_unusable() -> None:
    sample_rate_hz = 8
    fft_n = 64
    loaded = LoadedPostAnalysisRun(
        run_id="run-no-valid-bins",
        metadata=post_analysis_metadata("run-no-valid-bins", sample_rate_hz=sample_rate_hz),
        language="en",
        samples=sensor_frames_from_mappings(
            [
                {
                    "client_id": "sensor-a",
                    "t_s": fft_n / sample_rate_hz,
                    "sample_rate_hz": sample_rate_hz,
                    "vibration_strength_db": 0.0,
                    "dominant_freq_hz": 0.0,
                }
            ]
        ),
        raw_capture=_outcome_capture(
            "run-no-valid-bins", sample_rate_hz=sample_rate_hz, wave_hz=2.0
        ),
        total_summary_row_count=1,
        stride=1,
    )

    result = build_post_analysis_input(loaded)

    rebuilt = result.diagnostics_run.samples[0]
    assert result.raw_backed_summary_row_count == 0
    assert result.raw_replay.complete_window_count == 1
    assert result.raw_replay.fft_unusable_window_count == 1
    assert result.raw_replay.replay_confidence == "fallback"
    assert result.raw_replay.raw_capture_mode == "summary_only"
    assert result.raw_replay_window_coverages[0].reason == "fft_no_valid_bins"
    assert WARNING_CODE_RAW_REPLAY_FFT_UNUSABLE in warning_codes(result.raw_replay.warnings)
    assert rebuilt.vibration_strength_db is None
    assert rebuilt.dominant_freq_hz is None
    assert rebuilt.top_peaks == ()
    assert rebuilt.strength_bucket is None
    assert rebuilt.strength_peak_amp_g is None
    assert rebuilt.strength_floor_amp_g is None


def test_build_post_analysis_input_marks_fatal_raw_capture_loss_policy() -> None:
    raw_capture = _outcome_capture("run-fatal-drops")
    loss_stats = RawCaptureLossStats(queue_overflow_chunk_count=120)
    raw_capture = RawRunCapture(
        manifest=replace(
            raw_capture.manifest,
            sensor_losses=(RawCaptureSensorLossStats(client_id="sensor-a", losses=loss_stats),),
            losses=loss_stats,
        ),
        sensors=raw_capture.sensors,
    )
    loaded = LoadedPostAnalysisRun(
        run_id="run-fatal-drops",
        metadata=post_analysis_metadata("run-fatal-drops"),
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

    assert result.raw_replay.raw_capture_loss_policy_severity == "fatal"
    assert result.raw_replay.raw_capture_loss_policy_reason == "raw_capture_queue_overflow_fatal"
    assert WARNING_CODE_RAW_CAPTURE_LOSS_POLICY in warning_codes(result.raw_replay.warnings)
