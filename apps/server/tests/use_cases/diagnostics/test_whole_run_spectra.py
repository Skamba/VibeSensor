from __future__ import annotations

import json
from dataclasses import replace
from io import BytesIO
from math import pi

import numpy as np

from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.types.raw_capture import (
    RawCaptureChunkIndex,
    RawCaptureLossStats,
    RawCaptureManifest,
    RawCaptureSensorClockSync,
    RawCaptureSensorData,
    RawCaptureSensorManifest,
    RawRunCapture,
)
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.use_cases.diagnostics.whole_run_spectra import (
    WholeRunWindowSpectralSummary,
    build_whole_run_spectral_artifact_bundle,
)

_RUN_START_US = 1_000_000


def _metadata() -> RunMetadata:
    return run_metadata_from_mapping(
        {
            "run_id": "run-spectra",
            "start_time_utc": "2025-01-01T00:00:00Z",
            "sensor_model": "fixture-sensor",
            "raw_sample_rate_hz": 8,
            "sample_rate_hz": 8,
            "feature_interval_s": 0.5,
            "fft_window_size_samples": 8,
            "accel_scale_g_per_lsb": 0.001,
        }
    )


def _verified_sync() -> RawCaptureSensorClockSync:
    return RawCaptureSensorClockSync(
        clock_domain="server_monotonic",
        proof_state="verified",
        observed_monotonic_us=_RUN_START_US + 10_000,
        last_sync_monotonic_us=_RUN_START_US,
        sync_offset_us=0,
        sync_rtt_us=2_000,
        max_sync_age_us=15_000_000,
        max_sync_rtt_us=50_000,
    )


def _sine_samples(
    *,
    total_samples: int,
    freq_hz: float = 2.0,
    sample_rate_hz: int = 8,
    amplitude: float = 900.0,
    phase_rad: float = 0.0,
) -> np.ndarray:
    t = np.arange(total_samples, dtype=np.float64) / float(sample_rate_hz)
    x = np.round(amplitude * np.sin((2.0 * pi * freq_hz * t) + phase_rad)).astype(np.int16)
    y = np.zeros(total_samples, dtype=np.int16)
    z = np.zeros(total_samples, dtype=np.int16)
    return np.stack([x, y, z], axis=1)


def _make_sensor(
    *,
    client_id: str,
    sample_rate_hz: int,
    chunks: list[tuple[int, np.ndarray]],
    clock_sync: RawCaptureSensorClockSync | None = None,
) -> RawCaptureSensorData:
    append_start = 0
    chunk_indexes: list[RawCaptureChunkIndex] = []
    arrays: list[np.ndarray] = []
    for t0_us, chunk_samples in chunks:
        sample_count = int(chunk_samples.shape[0])
        chunk_indexes.append(
            RawCaptureChunkIndex(
                sample_start=append_start,
                sample_count=sample_count,
                t0_us=t0_us,
                byte_offset=append_start * 3 * 2,
            )
        )
        arrays.append(np.ascontiguousarray(chunk_samples, dtype=np.int16))
        append_start += sample_count
    stacked = np.vstack(arrays) if arrays else np.empty((0, 3), dtype=np.int16)
    manifest = RawCaptureSensorManifest(
        client_id=client_id,
        sample_rate_hz=sample_rate_hz,
        data_file=f"{client_id}.raw.i16le",
        index_file=f"{client_id}.index.jsonl",
        sample_count=int(stacked.shape[0]),
        chunk_count=len(chunk_indexes),
        bytes_written=int(stacked.shape[0] * 3 * 2),
        first_t0_us=chunks[0][0] if chunks else None,
        last_t0_us=chunks[-1][0] if chunks else None,
        clock_sync=clock_sync,
    )
    return RawCaptureSensorData(
        manifest=manifest,
        samples_i16=stacked,
        chunks=tuple(chunk_indexes),
    )


def _raw_capture(
    *sensors: RawCaptureSensorData,
    losses: RawCaptureLossStats | None = None,
) -> RawRunCapture:
    manifest = RawCaptureManifest(
        run_id="run-spectra",
        relative_dir="raw-runs/run-spectra",
        sensors=tuple(sensor.manifest for sensor in sensors),
        total_samples=sum(sensor.manifest.sample_count for sensor in sensors),
        total_bytes=sum(sensor.manifest.bytes_written for sensor in sensors),
        created_at="2025-01-01T00:00:00Z",
        run_start_monotonic_us=_RUN_START_US,
        losses=losses or RawCaptureLossStats(),
    )
    return RawRunCapture(manifest=manifest, sensors=tuple(sensors))


def _summary_rows(payload: bytes) -> list[dict[str, object]]:
    return [json.loads(line) for line in payload.decode("utf-8").splitlines()]


def _summaries(bundle, sensor_id: str) -> tuple[WholeRunWindowSpectralSummary, ...]:
    payload = bundle.artifact_contents[f"spectral-summary:{sensor_id}"]
    return tuple(WholeRunWindowSpectralSummary.from_mapping(row) for row in _summary_rows(payload))


def test_whole_run_spectra_are_deterministic_across_serial_and_parallel_execution() -> None:
    raw_capture = _raw_capture(
        _make_sensor(
            client_id="sensor-a",
            sample_rate_hz=8,
            chunks=[(_RUN_START_US, _sine_samples(total_samples=16))],
            clock_sync=_verified_sync(),
        ),
        _make_sensor(
            client_id="sensor-b",
            sample_rate_hz=8,
            chunks=[(_RUN_START_US, _sine_samples(total_samples=12, phase_rad=0.2))],
            clock_sync=_verified_sync(),
        ),
    )

    serial_result = build_whole_run_spectral_artifact_bundle(
        run_id="run-spectra",
        metadata=_metadata(),
        raw_capture=raw_capture,
        max_workers=1,
        chunk_window_count=2,
        created_at="2025-01-01T00:00:00Z",
    )
    parallel_result = build_whole_run_spectral_artifact_bundle(
        run_id="run-spectra",
        metadata=_metadata(),
        raw_capture=raw_capture,
        max_workers=2,
        chunk_window_count=2,
        created_at="2025-01-01T00:00:00Z",
    )

    assert serial_result.bundle is not None
    assert parallel_result.bundle is not None
    assert serial_result.bundle.manifest == parallel_result.bundle.manifest
    assert serial_result.bundle.artifact_contents == parallel_result.bundle.artifact_contents
    assert serial_result.coverage_summary == parallel_result.coverage_summary
    assert serial_result.bundle.manifest.total_window_count == 3
    assert [artifact.artifact_key for artifact in serial_result.bundle.manifest.artifacts] == [
        "spectral-grid:sensor-a",
        "spectral-matrix:sensor-a",
        "spectral-summary:sensor-a",
        "spectral-grid:sensor-b",
        "spectral-matrix:sensor-b",
        "spectral-summary:sensor-b",
    ]


def test_whole_run_spectra_align_sensor_windows_by_measurement_time() -> None:
    raw_capture = _raw_capture(
        _make_sensor(
            client_id="sensor-a",
            sample_rate_hz=8,
            chunks=[(_RUN_START_US, _sine_samples(total_samples=16))],
            clock_sync=_verified_sync(),
        ),
        _make_sensor(
            client_id="sensor-b",
            sample_rate_hz=8,
            chunks=[(_RUN_START_US + 500_000, _sine_samples(total_samples=16, phase_rad=0.3))],
            clock_sync=_verified_sync(),
        ),
    )

    result = build_whole_run_spectral_artifact_bundle(
        run_id="run-spectra",
        metadata=_metadata(),
        raw_capture=raw_capture,
        max_workers=1,
        chunk_window_count=2,
        created_at="2025-01-01T00:00:00Z",
    )

    assert result.bundle is not None
    assert result.window_plan is not None
    assert [window.sample_start for window in result.window_plan.windows] == [0, 4, 8, 12]

    sensor_a_rows = _summary_rows(result.bundle.artifact_contents["spectral-summary:sensor-a"])
    sensor_b_rows = _summary_rows(result.bundle.artifact_contents["spectral-summary:sensor-b"])

    assert [row["coverage_state"] for row in sensor_a_rows] == ["full", "full", "full", "missing"]
    assert [row["coverage_state"] for row in sensor_b_rows] == ["missing", "full", "full", "full"]
    assert sensor_b_rows[0]["coverage_reason"] == "window_before_capture"
    assert sensor_b_rows[1]["window_start_t_s"] == 0.5
    assert sensor_b_rows[1]["window_end_t_s"] == 1.5
    assert sensor_a_rows[1]["returned_sample_count"] == 8
    assert sensor_b_rows[1]["returned_sample_count"] == 8
    assert result.coverage_summary.missing_sensor_window_count == 2
    assert result.coverage_summary.full_sensor_window_count == 6


def test_whole_run_spectra_mark_gap_windows_partial() -> None:
    raw_capture = _raw_capture(
        _make_sensor(
            client_id="sensor-gap",
            sample_rate_hz=8,
            chunks=[
                (_RUN_START_US, _sine_samples(total_samples=8)),
                (_RUN_START_US + 1_500_000, _sine_samples(total_samples=8, phase_rad=0.5)),
            ],
            clock_sync=_verified_sync(),
        ),
    )

    result = build_whole_run_spectral_artifact_bundle(
        run_id="run-spectra",
        metadata=_metadata(),
        raw_capture=raw_capture,
        max_workers=1,
        chunk_window_count=4,
        created_at="2025-01-01T00:00:00Z",
    )

    assert result.bundle is not None
    rows = _summary_rows(result.bundle.artifact_contents["spectral-summary:sensor-gap"])
    assert [row["coverage_state"] for row in rows] == ["full", "partial", "partial", "full"]
    assert rows[1]["coverage_reason"] == "window_crosses_gap"
    assert rows[2]["coverage_reason"] == "window_crosses_gap"
    matrix = np.load(BytesIO(result.bundle.artifact_contents["spectral-matrix:sensor-gap"]))
    assert np.allclose(matrix[1], 0.0)
    assert np.allclose(matrix[2], 0.0)
    assert result.coverage_summary.partial_sensor_window_count == 2
    assert result.coverage_summary.gap_count == 1
    assert [warning.code for warning in result.coverage_summary.warnings] == [
        "whole_run_alignment_incomplete"
    ]


def test_whole_run_spectra_keep_contiguous_chunk_boundaries_full() -> None:
    raw_capture = _raw_capture(
        _make_sensor(
            client_id="sensor-contiguous",
            sample_rate_hz=8,
            chunks=[
                (_RUN_START_US, _sine_samples(total_samples=8)),
                (_RUN_START_US + 1_000_000, _sine_samples(total_samples=8, phase_rad=0.5)),
            ],
            clock_sync=_verified_sync(),
        ),
    )

    result = build_whole_run_spectral_artifact_bundle(
        run_id="run-spectra",
        metadata=_metadata(),
        raw_capture=raw_capture,
        max_workers=1,
        chunk_window_count=4,
        created_at="2025-01-01T00:00:00Z",
    )

    assert result.bundle is not None
    rows = _summary_rows(result.bundle.artifact_contents["spectral-summary:sensor-contiguous"])
    assert [row["coverage_state"] for row in rows] == ["full", "full", "full"]
    assert {row.get("coverage_reason") for row in rows} == {None}
    assert rows[1]["returned_sample_count"] == 8
    assert result.coverage_summary.partial_sensor_window_count == 0
    assert result.coverage_summary.gap_count == 0
    assert result.coverage_summary.coverage_confidence == "full"


def test_whole_run_spectra_missing_chunk_metadata_falls_back_to_warning() -> None:
    sensor = _make_sensor(
        client_id="sensor-metadata-missing",
        sample_rate_hz=8,
        chunks=[(_RUN_START_US, _sine_samples(total_samples=16))],
        clock_sync=_verified_sync(),
    )
    raw_capture = _raw_capture(replace(sensor, chunks=()))

    result = build_whole_run_spectral_artifact_bundle(
        run_id="run-spectra",
        metadata=_metadata(),
        raw_capture=raw_capture,
        max_workers=1,
        chunk_window_count=2,
        created_at="2025-01-01T00:00:00Z",
    )

    assert result.bundle is None
    assert result.window_plan is None
    assert result.coverage_summary.total_sensor_window_count == 0
    assert result.coverage_summary.unanchored_sensor_count == 1
    assert result.coverage_summary.coverage_confidence == "unavailable"
    assert [warning.code for warning in result.coverage_summary.warnings] == [
        "whole_run_alignment_incomplete"
    ]


def test_whole_run_spectra_mark_sample_rate_mismatch_missing() -> None:
    raw_capture = _raw_capture(
        _make_sensor(
            client_id="sensor-a",
            sample_rate_hz=8,
            chunks=[(_RUN_START_US, _sine_samples(total_samples=16))],
            clock_sync=_verified_sync(),
        ),
        _make_sensor(
            client_id="sensor-mismatch",
            sample_rate_hz=10,
            chunks=[(_RUN_START_US, _sine_samples(total_samples=16, sample_rate_hz=10))],
            clock_sync=_verified_sync(),
        ),
    )

    result = build_whole_run_spectral_artifact_bundle(
        run_id="run-spectra",
        metadata=_metadata(),
        raw_capture=raw_capture,
        max_workers=1,
        chunk_window_count=2,
        created_at="2025-01-01T00:00:00Z",
    )

    assert result.bundle is not None
    mismatch_rows = _summary_rows(
        result.bundle.artifact_contents["spectral-summary:sensor-mismatch"]
    )
    assert {row["coverage_state"] for row in mismatch_rows} == {"missing"}
    assert {row["coverage_reason"] for row in mismatch_rows} == {"sample_rate_mismatch"}
    assert result.coverage_summary.sample_rate_mismatch_sensor_count == 1
    assert result.coverage_summary.coverage_confidence == "partial"
