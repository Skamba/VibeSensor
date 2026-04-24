from __future__ import annotations

import math

import numpy as np
import pytest

from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.fft_analysis import SpectralAnalysisComputer, medfilt3
from vibesensor.shared.run_context_warning import (
    WARNING_CODE_RAW_REPLAY_COVERAGE_INCOMPLETE,
    WARNING_CODE_RAW_REPLAY_LEGACY_FALLBACK,
    WARNING_CODE_RAW_REPLAY_TIMING_FALLBACK,
)
from vibesensor.shared.types.raw_capture import (
    RawCaptureChunkIndex,
    RawCaptureManifest,
    RawCaptureSensorData,
    RawCaptureSensorManifest,
    RawRunCapture,
)
from vibesensor.use_cases.run import raw_capture_replay
from vibesensor.use_cases.run.post_analysis_input import build_post_analysis_input
from vibesensor.use_cases.run.post_analysis_loader import LoadedPostAnalysisRun

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


def _sample_t_s(*, raw_start_offset_us: int, sample_end: int) -> float:
    return (
        float(raw_start_offset_us) + (float(sample_end) / float(_SAMPLE_RATE_HZ) * 1_000_000.0)
    ) / 1_000_000.0


def _analysis_window_end_us(*, raw_start_offset_us: int, sample_end: int) -> int:
    return int(
        raw_start_offset_us + (float(sample_end) / float(_SAMPLE_RATE_HZ) * 1_000_000.0),
    )


def _raw_capture(
    run_id: str,
    *,
    sensors: list[tuple[str, list[tuple[int, np.ndarray]]]],
    run_start_monotonic_us: int | None = _RUN_START_MONOTONIC_US,
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
        run_start_monotonic_us=run_start_monotonic_us,
    )
    return RawRunCapture(manifest=manifest, sensors=tuple(sensor_rows))


def _shared_strength_metrics(window_i16: np.ndarray) -> dict[str, object]:
    window_f32 = window_i16.astype(np.float32, copy=True) * np.float32(0.001)
    computer = SpectralAnalysisComputer(
        fft_n=_FFT_N,
        spectrum_min_hz=5.0,
        spectrum_max_hz=200.0,
    )
    return computer.compute_fft_spectrum(
        medfilt3(window_f32.T),
        _SAMPLE_RATE_HZ,
        spike_filter_enabled=False,
    )["strength_metrics"]


def test_build_post_analysis_input_aligns_raw_replay_from_run_start_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_start_offset_us = 100_000
    replay_window = _wave(32.0, _FFT_N)
    raw_capture = _raw_capture(
        "run-anchor",
        sensors=[
            (
                "sensor-a",
                [
                    (
                        _RUN_START_MONOTONIC_US + raw_start_offset_us,
                        np.vstack([replay_window, _wave(88.0, 160)]),
                    )
                ],
            )
        ],
    )
    loaded = LoadedPostAnalysisRun(
        run_id="run-anchor",
        metadata=_metadata("run-anchor"),
        language="en",
        samples=sensor_frames_from_mappings(
            [
                {
                    "client_id": "sensor-a",
                    "t_s": _sample_t_s(raw_start_offset_us=raw_start_offset_us, sample_end=_FFT_N),
                    "sample_rate_hz": _SAMPLE_RATE_HZ,
                    "vibration_strength_db": 0.0,
                    "dominant_freq_hz": 0.0,
                }
            ]
        ),
        raw_capture=raw_capture,
        total_sample_count=1,
        stride=1,
    )
    expected = _shared_strength_metrics(replay_window)
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

    rebuilt = result.samples[0]
    assert result.raw_backed_sample_count == 1
    assert result.raw_replay.raw_capture_mode == "raw_backed"
    assert result.raw_replay.complete_window_count == 1
    assert calls == [_SAMPLE_RATE_HZ]
    assert rebuilt.dominant_freq_hz is not None
    assert 25.0 <= rebuilt.dominant_freq_hz <= 40.0
    assert float(rebuilt.dominant_freq_hz) == pytest.approx(
        float(expected["top_peaks"][0]["hz"]),
        abs=0.5,
    )
    assert float(rebuilt.vibration_strength_db or 0.0) == pytest.approx(
        float(expected["vibration_strength_db"] or 0.0),
        abs=1e-6,
    )


def test_build_post_analysis_input_replays_each_sensor_on_its_own_timeline() -> None:
    sensor_a_offset_us = 100_000
    sensor_b_offset_us = 140_000
    raw_capture = _raw_capture(
        "run-offsets",
        sensors=[
            (
                "sensor-a",
                [
                    (
                        _RUN_START_MONOTONIC_US + sensor_a_offset_us,
                        np.vstack([_wave(28.0, 96), _wave(86.0, 160)]),
                    )
                ],
            ),
            (
                "sensor-b",
                [
                    (
                        _RUN_START_MONOTONIC_US + sensor_b_offset_us,
                        np.vstack([_wave(52.0, _FFT_N), _wave(92.0, 192)]),
                    )
                ],
            ),
        ],
    )
    sample_t_s = 0.22
    loaded = LoadedPostAnalysisRun(
        run_id="run-offsets",
        metadata=_metadata("run-offsets"),
        language="en",
        samples=sensor_frames_from_mappings(
            [
                {
                    "client_id": "sensor-a",
                    "t_s": sample_t_s,
                    "sample_rate_hz": _SAMPLE_RATE_HZ,
                    "vibration_strength_db": 0.0,
                    "dominant_freq_hz": 0.0,
                },
                {
                    "client_id": "sensor-b",
                    "t_s": sample_t_s,
                    "sample_rate_hz": _SAMPLE_RATE_HZ,
                    "vibration_strength_db": 0.0,
                    "dominant_freq_hz": 0.0,
                },
            ]
        ),
        raw_capture=raw_capture,
        total_sample_count=2,
        stride=1,
    )

    result = build_post_analysis_input(loaded)

    by_sensor = {sample.client_id: sample for sample in result.samples}
    assert result.raw_backed_sample_count == 2
    assert by_sensor["sensor-a"].dominant_freq_hz is not None
    assert by_sensor["sensor-b"].dominant_freq_hz is not None
    assert 20.0 <= float(by_sensor["sensor-a"].dominant_freq_hz) <= 35.0
    assert 45.0 <= float(by_sensor["sensor-b"].dominant_freq_hz) <= 60.0


def test_build_post_analysis_input_prefers_explicit_analysis_window_over_flush_time() -> None:
    raw_start_offset_us = 100_000
    aligned_window = _wave(32.0, _FFT_N)
    later_window = _wave(88.0, _FFT_N)
    raw_capture = _raw_capture(
        "run-delayed-flush",
        sensors=[
            (
                "sensor-a",
                [
                    (
                        _RUN_START_MONOTONIC_US + raw_start_offset_us,
                        np.vstack([aligned_window, later_window, _wave(96.0, 96)]),
                    )
                ],
            )
        ],
    )
    loaded = LoadedPostAnalysisRun(
        run_id="run-delayed-flush",
        metadata=_metadata("run-delayed-flush"),
        language="en",
        samples=sensor_frames_from_mappings(
            [
                {
                    "client_id": "sensor-a",
                    "t_s": 0.24,
                    "analysis_window_end_us": _analysis_window_end_us(
                        raw_start_offset_us=raw_start_offset_us,
                        sample_end=_FFT_N,
                    ),
                    "sample_rate_hz": _SAMPLE_RATE_HZ,
                    "vibration_strength_db": 0.0,
                    "dominant_freq_hz": 0.0,
                }
            ]
        ),
        raw_capture=raw_capture,
        total_sample_count=1,
        stride=1,
    )

    result = build_post_analysis_input(loaded)

    rebuilt = result.samples[0]
    assert result.raw_backed_sample_count == 1
    assert result.raw_replay.timing_fallback_count == 0
    assert result.raw_replay.warnings == ()
    assert rebuilt.dominant_freq_hz is not None
    assert 25.0 <= float(rebuilt.dominant_freq_hz) <= 40.0


def test_build_post_analysis_input_marks_gap_windows_partial_and_falls_back() -> None:
    raw_start_offset_us = 100_000
    first_chunk = _wave(34.0, _FFT_N)
    second_chunk = _wave(74.0, _FFT_N)
    raw_capture = _raw_capture(
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
        metadata=_metadata("run-gap"),
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
        total_sample_count=2,
        stride=1,
    )

    result = build_post_analysis_input(loaded)

    assert result.raw_backed_sample_count == 1
    assert result.raw_replay.raw_capture_mode == "partial_raw_backed"
    assert result.raw_replay.partial_window_count == 1
    assert result.raw_replay.gap_count == 1
    assert [warning.code for warning in result.raw_replay.warnings] == [
        WARNING_CODE_RAW_REPLAY_TIMING_FALLBACK,
        WARNING_CODE_RAW_REPLAY_COVERAGE_INCOMPLETE,
    ]
    assert [coverage.coverage_state for coverage in result.raw_replay_window_coverages] == [
        "complete",
        "partial",
    ]
    assert result.samples[1].vibration_strength_db == 12.0
    assert result.samples[1].dominant_freq_hz == 14.0


def test_build_post_analysis_input_warns_when_replay_falls_back_to_legacy_sample_time() -> None:
    raw_start_offset_us = 100_000
    replay_window = _wave(36.0, _FFT_N)
    raw_capture = _raw_capture(
        "run-legacy-sample-time",
        sensors=[
            (
                "sensor-a",
                [
                    (
                        _RUN_START_MONOTONIC_US + raw_start_offset_us,
                        np.vstack([replay_window, _wave(82.0, 160)]),
                    )
                ],
            )
        ],
    )
    loaded = LoadedPostAnalysisRun(
        run_id="run-legacy-sample-time",
        metadata=_metadata("run-legacy-sample-time"),
        language="en",
        samples=sensor_frames_from_mappings(
            [
                {
                    "client_id": "sensor-a",
                    "t_s": _sample_t_s(raw_start_offset_us=raw_start_offset_us, sample_end=_FFT_N),
                    "sample_rate_hz": _SAMPLE_RATE_HZ,
                    "vibration_strength_db": 0.0,
                    "dominant_freq_hz": 0.0,
                }
            ]
        ),
        raw_capture=raw_capture,
        total_sample_count=1,
        stride=1,
    )

    result = build_post_analysis_input(loaded)

    assert result.raw_backed_sample_count == 1
    assert result.raw_replay.timing_fallback_count == 1
    assert [warning.code for warning in result.raw_replay.warnings] == [
        WARNING_CODE_RAW_REPLAY_TIMING_FALLBACK
    ]
    assert result.raw_replay_window_coverages[0].reason == "timing_fallback"


def test_build_post_analysis_input_falls_back_for_legacy_raw_capture_without_anchor() -> None:
    raw_start_offset_us = 100_000
    raw_capture = _raw_capture(
        "run-legacy",
        sensors=[
            (
                "sensor-a",
                [
                    (
                        _RUN_START_MONOTONIC_US + raw_start_offset_us,
                        np.vstack([_wave(36.0, _FFT_N), _wave(80.0, 96)]),
                    )
                ],
            )
        ],
        run_start_monotonic_us=None,
    )
    loaded = LoadedPostAnalysisRun(
        run_id="run-legacy",
        metadata=_metadata("run-legacy"),
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
        total_sample_count=1,
        stride=1,
    )

    result = build_post_analysis_input(loaded)

    assert result.raw_backed_sample_count == 0
    assert result.raw_replay.raw_capture_mode == "summary_only"
    assert result.raw_replay.replay_confidence == "fallback"
    assert result.raw_replay.unanchored_sensor_count == 1
    assert [warning.code for warning in result.raw_replay.warnings] == [
        WARNING_CODE_RAW_REPLAY_LEGACY_FALLBACK
    ]
    assert result.samples[0].vibration_strength_db == 11.0
    assert result.samples[0].dominant_freq_hz == 13.0
