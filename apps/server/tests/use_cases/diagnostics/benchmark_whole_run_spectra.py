"""Explicit pytest-benchmark suite for whole-run raw-range and spectral hot paths.

These are opt-in explicit benchmarks (``benchmark_*.py`` filenames are not
collected under the default ``test_*`` pattern). Invoke with::

    pytest apps/server/tests/use_cases/diagnostics/benchmark_whole_run_spectra.py \
        --benchmark-only -o addopts='' \
        --benchmark-columns=min,mean,median,stddev,rounds

The benchmark dataset mirrors the intended production shape for #3085:

- four sensors
- 800 Hz raw sample rate
- five minutes of raw capture
- ``FFT_N=2048`` and ``feature_interval_s=1.0``

This keeps the sweep representative of Pi-sized runs while remaining opt-in.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import pi
from pathlib import Path

import numpy as np
import pytest
from test_support.history_db_lifecycle import (
    build_history_db,
    create_recording_run,
    make_run_metadata,
)

from vibesensor.shared.constants.dsp import FFT_N
from vibesensor.shared.types.raw_capture import (
    RawCaptureChunk,
    RawCaptureManifest,
    RawCaptureSensorRange,
)
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.use_cases.diagnostics.whole_run_spectra import (
    build_whole_run_spectral_artifact_bundle,
)
from vibesensor.use_cases.diagnostics.whole_run_windows import (
    WholeRunWindowPlan,
    plan_whole_run_windows,
)

_SAMPLE_RATE_HZ = 800
_FEATURE_INTERVAL_S = 1.0
_DURATION_S = 300
_TOTAL_SAMPLES = _SAMPLE_RATE_HZ * _DURATION_S
_SENSOR_COUNT = 4
_RAW_CHUNK_SAMPLES = 1024
_CLIENT_IDS = tuple(f"sensor-{idx:02d}" for idx in range(_SENSOR_COUNT))
_BASE_FREQS_HZ = (23.0, 37.0, 51.0, 67.0)


def _sensor_samples(*, total_samples: int, freq_hz: float, phase_rad: float) -> np.ndarray:
    t = np.arange(total_samples, dtype=np.float64) / _SAMPLE_RATE_HZ
    x = (0.16 * np.sin((2.0 * pi * freq_hz * t) + phase_rad) * 256.0).astype(np.int16)
    y = (0.10 * np.sin((2.0 * pi * (freq_hz + 11.0) * t) + (phase_rad * 0.5)) * 256.0).astype(
        np.int16
    )
    z = (0.06 * np.sin((2.0 * pi * (freq_hz * 0.5) * t) - phase_rad) * 256.0).astype(np.int16)
    return np.stack([x, y, z], axis=1)


def _append_chunk(
    db,
    *,
    run_id: str,
    client_id: str,
    sample_start: int,
    samples: np.ndarray,
) -> None:
    t0_us = int(sample_start * (1_000_000 / _SAMPLE_RATE_HZ))
    chunk = RawCaptureChunk(
        client_id=client_id,
        sample_rate_hz=_SAMPLE_RATE_HZ,
        t0_us=t0_us,
        sample_count=int(samples.shape[0]),
        samples_i16le=np.ascontiguousarray(samples, dtype=np.int16).tobytes(order="C"),
    )
    db.run_repository._run_sync(db.run_repository.aappend_raw_capture_chunk(run_id, chunk))


@dataclass(frozen=True, slots=True)
class _WholeRunBenchmarkFixture:
    db: object
    run_id: str
    metadata: RunMetadata
    raw_capture_manifest: RawCaptureManifest
    plan: WholeRunWindowPlan

    def load_sensor_range(
        self,
        *,
        client_id: str,
        sample_start: int,
        sample_count: int,
    ) -> RawCaptureSensorRange | None:
        return self.db.run_repository._run_sync(
            self.db.run_repository.aload_raw_capture_sensor_range(
                self.run_id,
                client_id,
                sample_start=sample_start,
                sample_count=sample_count,
            )
        )


@pytest.fixture(scope="session")
def whole_run_fixture(tmp_path_factory: pytest.TempPathFactory) -> _WholeRunBenchmarkFixture:
    tmp_path = tmp_path_factory.mktemp("whole-run-bench")
    db = build_history_db(Path(tmp_path))
    run_id = "run-benchmark"
    metadata = make_run_metadata(
        run_id,
        fft_window_size_samples=FFT_N,
        feature_interval_s=_FEATURE_INTERVAL_S,
        accel_scale_g_per_lsb=1.0 / 256.0,
    )
    create_recording_run(db, run_id, metadata=metadata)
    for client_id, freq_hz in zip(_CLIENT_IDS, _BASE_FREQS_HZ, strict=True):
        samples = _sensor_samples(
            total_samples=_TOTAL_SAMPLES,
            freq_hz=freq_hz,
            phase_rad=float(len(client_id)) * 0.17,
        )
        for sample_start in range(0, samples.shape[0], _RAW_CHUNK_SAMPLES):
            chunk = samples[sample_start : sample_start + _RAW_CHUNK_SAMPLES]
            _append_chunk(
                db,
                run_id=run_id,
                client_id=client_id,
                sample_start=sample_start,
                samples=chunk,
            )
    raw_capture_manifest = db.run_repository._run_sync(
        db.run_repository.afinalize_raw_capture(run_id)
    )
    assert raw_capture_manifest is not None
    plan = plan_whole_run_windows(metadata=metadata, total_sample_count=_TOTAL_SAMPLES)
    return _WholeRunBenchmarkFixture(
        db=db,
        run_id=run_id,
        metadata=metadata,
        raw_capture_manifest=raw_capture_manifest,
        plan=plan,
    )


@pytest.mark.benchmark(group="whole-run-raw-range-reader")
def test_whole_run_raw_range_reader_benchmark(
    benchmark,
    whole_run_fixture: _WholeRunBenchmarkFixture,
) -> None:
    sensor_id = _CLIENT_IDS[0]

    def _read_all_windows() -> int:
        total_returned_samples = 0
        for window in whole_run_fixture.plan.windows:
            result = whole_run_fixture.load_sensor_range(
                client_id=sensor_id,
                sample_start=window.sample_start,
                sample_count=window.sample_count,
            )
            assert result is not None
            total_returned_samples += result.returned_sample_count
        return total_returned_samples

    benchmark.extra_info["duration_s"] = _DURATION_S
    benchmark.extra_info["sensor_count"] = _SENSOR_COUNT
    benchmark.extra_info["window_count"] = whole_run_fixture.plan.total_window_count
    benchmark.extra_info["raw_chunk_samples"] = _RAW_CHUNK_SAMPLES
    total_returned_samples = benchmark.pedantic(
        _read_all_windows,
        iterations=1,
        rounds=3,
        warmup_rounds=1,
    )

    assert total_returned_samples == whole_run_fixture.plan.total_window_count * FFT_N


@pytest.mark.benchmark(group="whole-run-spectral-executor")
@pytest.mark.parametrize(
    ("max_workers", "chunk_window_count"),
    [
        pytest.param(1, 32, id="sequential-32"),
        pytest.param(4, 16, id="parallel-16"),
        pytest.param(4, 32, id="parallel-32"),
        pytest.param(4, 64, id="parallel-64"),
    ],
)
def test_whole_run_spectral_executor_benchmark(
    benchmark,
    whole_run_fixture: _WholeRunBenchmarkFixture,
    max_workers: int,
    chunk_window_count: int,
) -> None:
    def _build_bundle():
        return build_whole_run_spectral_artifact_bundle(
            run_id=whole_run_fixture.run_id,
            metadata=whole_run_fixture.metadata,
            raw_capture_manifest=whole_run_fixture.raw_capture_manifest,
            load_sensor_range=whole_run_fixture.load_sensor_range,
            max_workers=max_workers,
            chunk_window_count=chunk_window_count,
            created_at="2026-01-01T00:00:00Z",
        )

    benchmark.extra_info["duration_s"] = _DURATION_S
    benchmark.extra_info["sensor_count"] = _SENSOR_COUNT
    benchmark.extra_info["window_count"] = whole_run_fixture.plan.total_window_count
    benchmark.extra_info["max_workers"] = max_workers
    benchmark.extra_info["chunk_window_count"] = chunk_window_count
    bundle = benchmark.pedantic(
        _build_bundle,
        iterations=1,
        rounds=2,
        warmup_rounds=0,
    )

    assert bundle is not None
    assert bundle.manifest.total_window_count == whole_run_fixture.plan.total_window_count
    assert len(bundle.manifest.artifacts) == _SENSOR_COUNT * 3
