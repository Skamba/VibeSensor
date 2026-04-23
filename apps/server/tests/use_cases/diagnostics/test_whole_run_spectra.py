from __future__ import annotations

import json
from io import BytesIO

import numpy as np

from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.types.raw_capture import (
    RawCaptureManifest,
    RawCaptureSensorManifest,
    RawCaptureSensorRange,
)
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.use_cases.diagnostics.whole_run_spectra import (
    build_whole_run_spectral_artifact_bundle,
)


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


def _raw_manifest() -> RawCaptureManifest:
    return RawCaptureManifest(
        run_id="run-spectra",
        relative_dir="raw-runs/run-spectra",
        sensors=(
            RawCaptureSensorManifest(
                client_id="sensor-a",
                sample_rate_hz=8,
                data_file="sensor-a.raw.i16le",
                index_file="sensor-a.index.jsonl",
                sample_count=16,
                chunk_count=1,
                bytes_written=16 * 3 * 2,
            ),
            RawCaptureSensorManifest(
                client_id="sensor-b",
                sample_rate_hz=8,
                data_file="sensor-b.raw.i16le",
                index_file="sensor-b.index.jsonl",
                sample_count=12,
                chunk_count=1,
                bytes_written=12 * 3 * 2,
            ),
        ),
        total_samples=28,
        total_bytes=(16 + 12) * 3 * 2,
        created_at="2025-01-01T00:00:00Z",
    )


def _sensor_samples() -> dict[str, np.ndarray]:
    base = np.array(
        [
            [0, 0, 0],
            [1000, 100, 0],
            [0, 0, 0],
            [-1000, -100, 0],
            [0, 0, 0],
            [1000, 100, 0],
            [0, 0, 0],
            [-1000, -100, 0],
        ],
        dtype=np.int16,
    )
    return {
        "sensor-a": np.vstack([base, base]),
        "sensor-b": np.vstack([base, base[:4]]),
    }


def _load_sensor_range_factory(samples_by_sensor: dict[str, np.ndarray]):
    manifest = _raw_manifest()

    def _load_sensor_range(
        *,
        client_id: str,
        sample_start: int,
        sample_count: int,
    ) -> RawCaptureSensorRange | None:
        sensor_samples = samples_by_sensor.get(client_id)
        sensor_manifest = manifest.sensor_manifest(client_id)
        if sensor_samples is None or sensor_manifest is None:
            return RawCaptureSensorRange.missing(
                client_id=client_id,
                requested_sample_start=sample_start,
                requested_sample_count=sample_count,
            )
        available = sensor_samples.shape[0]
        if sample_start >= available:
            return RawCaptureSensorRange(
                client_id=client_id,
                requested_sample_start=sample_start,
                requested_sample_count=sample_count,
                coverage_state="empty",
                samples_i16=np.empty((0, 3), dtype=np.int16),
                manifest=sensor_manifest,
                returned_sample_start=sample_start,
            )
        actual_end = min(sample_start + sample_count, available)
        samples_i16 = sensor_samples[sample_start:actual_end].copy()
        coverage_state = "full" if samples_i16.shape[0] == sample_count else "partial"
        return RawCaptureSensorRange(
            client_id=client_id,
            requested_sample_start=sample_start,
            requested_sample_count=sample_count,
            coverage_state=coverage_state,
            samples_i16=samples_i16,
            manifest=sensor_manifest,
            returned_sample_start=sample_start,
        )

    return _load_sensor_range


def test_whole_run_spectra_are_deterministic_across_serial_and_parallel_execution() -> None:
    metadata = _metadata()
    raw_manifest = _raw_manifest()
    load_sensor_range = _load_sensor_range_factory(_sensor_samples())

    serial_bundle = build_whole_run_spectral_artifact_bundle(
        run_id="run-spectra",
        metadata=metadata,
        raw_capture_manifest=raw_manifest,
        load_sensor_range=load_sensor_range,
        max_workers=1,
        chunk_window_count=2,
        created_at="2025-01-01T00:00:00Z",
    )
    parallel_bundle = build_whole_run_spectral_artifact_bundle(
        run_id="run-spectra",
        metadata=metadata,
        raw_capture_manifest=raw_manifest,
        load_sensor_range=load_sensor_range,
        max_workers=2,
        chunk_window_count=2,
        created_at="2025-01-01T00:00:00Z",
    )

    assert serial_bundle is not None
    assert parallel_bundle is not None
    assert serial_bundle.manifest == parallel_bundle.manifest
    assert serial_bundle.artifact_contents == parallel_bundle.artifact_contents
    assert serial_bundle.manifest.total_window_count == 3
    assert [artifact.artifact_key for artifact in serial_bundle.manifest.artifacts] == [
        "spectral-grid:sensor-a",
        "spectral-matrix:sensor-a",
        "spectral-summary:sensor-a",
        "spectral-grid:sensor-b",
        "spectral-matrix:sensor-b",
        "spectral-summary:sensor-b",
    ]


def test_whole_run_spectra_emit_explicit_partial_coverage_rows() -> None:
    bundle = build_whole_run_spectral_artifact_bundle(
        run_id="run-spectra",
        metadata=_metadata(),
        raw_capture_manifest=_raw_manifest(),
        load_sensor_range=_load_sensor_range_factory(_sensor_samples()),
        max_workers=1,
        chunk_window_count=2,
        created_at="2025-01-01T00:00:00Z",
    )

    assert bundle is not None
    summary_rows = [
        json.loads(line)
        for line in bundle.artifact_contents["spectral-summary:sensor-b"]
        .decode("utf-8")
        .splitlines()
    ]
    matrix = np.load(BytesIO(bundle.artifact_contents["spectral-matrix:sensor-b"]))

    assert [row["coverage_state"] for row in summary_rows] == ["full", "full", "partial"]
    assert summary_rows[-1]["returned_sample_start"] == 8
    assert summary_rows[-1]["returned_sample_count"] == 4
    assert np.allclose(matrix[-1], 0.0)
