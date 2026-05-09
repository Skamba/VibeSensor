from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from test_support.history_db_lifecycle import build_history_db, create_recording_run

from vibesensor.shared.types.raw_capture import RawCaptureChunk
from vibesensor.shared.types.run_schema import RunMetadata, RunSensorMetadata
from vibesensor.use_cases.diagnostics.post_run_raw_windows import (
    PostRunRawWindowIteratorConfig,
    prepare_post_run_raw_window_iterator,
)


def _append_chunk(
    db,
    *,
    run_id: str,
    client_id: str,
    t0_us: int,
    samples: np.ndarray,
    sample_rate_hz: int = 4,
) -> None:
    chunk = RawCaptureChunk(
        client_id=client_id,
        sample_rate_hz=sample_rate_hz,
        t0_us=t0_us,
        sample_count=int(samples.shape[0]),
        samples_i16le=np.ascontiguousarray(samples, dtype=np.int16).tobytes(order="C"),
    )
    db.run_repository._run_sync(db.run_repository.aappend_raw_capture_chunk(run_id, chunk))


def _finalize_raw_capture(db, run_id: str):
    return db.run_repository._run_sync(db.run_repository.afinalize_raw_capture(run_id))


async def _collect_windows(iterator) -> list:
    return [window async for window in iterator.iter_windows()]


def _samples(rows: int, *, offset: int = 0) -> np.ndarray:
    x = np.arange(offset, offset + rows, dtype=np.int16)
    y = x + 100
    z = x + 200
    return np.stack([x, y, z], axis=1)


def _create_run_with_sensor_metadata(db, run_id: str) -> None:
    metadata = RunMetadata.create(
        run_id=run_id,
        start_time_utc="2026-01-01T00:00:00Z",
        sensor_model="ADXL345",
        raw_sample_rate_hz=4,
        configured_raw_sample_rate_hz=4,
        feature_interval_s=0.5,
        fft_window_size_samples=4,
        accel_scale_g_per_lsb=0.001,
        sensor_snapshots=(
            RunSensorMetadata(sensor_id="sensor-a", location_code="front_left"),
            RunSensorMetadata(sensor_id="sensor-b", location_code="rear_right"),
        ),
    )
    create_recording_run(
        db,
        run_id,
        metadata=metadata,
    )


def test_post_run_raw_window_iterator_streams_configured_sensor_ranges(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    _create_run_with_sensor_metadata(db, "run-windows")
    _append_chunk(db, run_id="run-windows", client_id="sensor-a", t0_us=0, samples=_samples(6))
    _append_chunk(
        db,
        run_id="run-windows",
        client_id="sensor-b",
        t0_us=0,
        samples=_samples(4, offset=20),
    )
    assert _finalize_raw_capture(db, "run-windows") is not None

    iterator = db.run_repository._run_sync(
        prepare_post_run_raw_window_iterator(
            db.run_repository,
            "run-windows",
            config=PostRunRawWindowIteratorConfig(
                window_size_s=1.0,
                overlap_pct=0.5,
                min_valid_samples_pct=0.5,
            ),
        )
    )
    windows = db.run_repository._run_sync(_collect_windows(iterator))

    assert iterator.plan is not None
    assert [window.window.sample_start for window in windows] == [0, 2, 4]
    assert [window.window.sample_end for window in windows] == [4, 6, 8]
    assert [sensor.client_id for sensor in windows[0].sensors] == ["sensor-a", "sensor-b"]
    assert windows[0].sensors[0].location == "front_left"
    assert windows[0].sensors[0].axis_x_i16.tolist() == [0, 1, 2, 3]
    assert windows[1].sensors[0].axis_y_i16.tolist() == [102, 103, 104, 105]
    assert "partial_window" in windows[2].sensors[0].data_quality_flags
    assert "missing_samples" in windows[2].sensors[0].data_quality_flags
    assert "low_sample_count" in windows[2].sensors[1].data_quality_flags


def test_post_run_raw_window_iterator_flags_sensor_clipping(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    _create_run_with_sensor_metadata(db, "run-clipping")
    samples = _samples(4)
    samples[:3, 0] = 32767
    _append_chunk(db, run_id="run-clipping", client_id="sensor-a", t0_us=0, samples=samples)
    assert _finalize_raw_capture(db, "run-clipping") is not None

    iterator = db.run_repository._run_sync(
        prepare_post_run_raw_window_iterator(
            db.run_repository,
            "run-clipping",
            config=PostRunRawWindowIteratorConfig(
                window_size_s=1.0,
                overlap_pct=0.0,
                min_valid_samples_pct=0.5,
            ),
        )
    )
    windows = db.run_repository._run_sync(_collect_windows(iterator))

    assert "sensor_clipping" in windows[0].sensors[0].data_quality_flags


def test_post_run_raw_window_iterator_uses_manifest_range_reads_not_full_capture(
    tmp_path: Path,
) -> None:
    db = build_history_db(tmp_path)
    _create_run_with_sensor_metadata(db, "run-stream")
    _append_chunk(db, run_id="run-stream", client_id="sensor-a", t0_us=0, samples=_samples(6))
    assert _finalize_raw_capture(db, "run-stream") is not None

    class CountingRepository:
        def __init__(self, wrapped) -> None:
            self.wrapped = wrapped
            self.range_reads: list[tuple[str, int, int]] = []

        async def aget_run_metadata(self, run_id: str):
            return await self.wrapped.aget_run_metadata(run_id)

        async def aget_raw_capture_manifest(self, run_id: str):
            return await self.wrapped.aget_raw_capture_manifest(run_id)

        async def aload_raw_capture_sensor_range(
            self,
            run_id: str,
            client_id: str,
            *,
            sample_start: int,
            sample_count: int,
        ):
            self.range_reads.append((client_id, sample_start, sample_count))
            return await self.wrapped.aload_raw_capture_sensor_range(
                run_id,
                client_id,
                sample_start=sample_start,
                sample_count=sample_count,
            )

    repository = CountingRepository(db.run_repository)
    iterator = db.run_repository._run_sync(
        prepare_post_run_raw_window_iterator(
            repository,
            "run-stream",
            config=PostRunRawWindowIteratorConfig(
                window_size_s=1.0,
                overlap_pct=0.5,
                min_valid_samples_pct=0.5,
                sensor_ids=("sensor-a",),
            ),
        )
    )
    db.run_repository._run_sync(_collect_windows(iterator))

    assert repository.range_reads == [
        ("sensor-a", 0, 4),
        ("sensor-a", 2, 4),
        ("sensor-a", 4, 4),
    ]


def test_post_run_raw_window_iterator_returns_warning_for_missing_artifact(
    tmp_path: Path,
) -> None:
    db = build_history_db(tmp_path)
    _create_run_with_sensor_metadata(db, "run-missing")

    iterator = db.run_repository._run_sync(
        prepare_post_run_raw_window_iterator(db.run_repository, "run-missing")
    )
    windows = db.run_repository._run_sync(_collect_windows(iterator))

    assert windows == []
    assert [warning.code for warning in iterator.warnings] == ["missing_raw_capture_manifest"]


def test_post_run_raw_window_iterator_flags_timestamp_gaps(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    _create_run_with_sensor_metadata(db, "run-gap")
    _append_chunk(db, run_id="run-gap", client_id="sensor-a", t0_us=0, samples=_samples(4))
    _append_chunk(
        db,
        run_id="run-gap",
        client_id="sensor-a",
        t0_us=1_000_000,
        samples=_samples(4, offset=4),
    )
    assert _finalize_raw_capture(db, "run-gap") is not None

    class GapRangeRepository:
        async def aget_run_metadata(self, run_id: str):
            return await db.run_repository.aget_run_metadata(run_id)

        async def aget_raw_capture_manifest(self, run_id: str):
            return await db.run_repository.aget_raw_capture_manifest(run_id)

        async def aload_raw_capture_sensor_range(
            self,
            run_id: str,
            client_id: str,
            *,
            sample_start: int,
            sample_count: int,
        ):
            raw_range = await db.run_repository.aload_raw_capture_sensor_range(
                run_id,
                client_id,
                sample_start=sample_start,
                sample_count=sample_count,
            )
            if raw_range is None or len(raw_range.chunks) < 2:
                return raw_range
            shifted_chunk = replace(raw_range.chunks[1], t0_us=2_000_000)
            return replace(raw_range, chunks=(raw_range.chunks[0], shifted_chunk))

    iterator = db.run_repository._run_sync(
        prepare_post_run_raw_window_iterator(
            GapRangeRepository(),
            "run-gap",
            config=PostRunRawWindowIteratorConfig(
                window_size_s=1.0,
                overlap_pct=0.5,
                min_valid_samples_pct=0.5,
            ),
        )
    )
    windows = db.run_repository._run_sync(_collect_windows(iterator))

    assert "timestamp_gap" in windows[1].sensors[0].data_quality_flags
    assert "timestamp_gap" in {warning.code for warning in windows[1].warnings}


def test_post_run_raw_window_iterator_rejects_unsupported_manifest_schema(
    tmp_path: Path,
) -> None:
    db = build_history_db(tmp_path)
    _create_run_with_sensor_metadata(db, "run-schema")
    _append_chunk(db, run_id="run-schema", client_id="sensor-a", t0_us=0, samples=_samples(4))
    manifest = _finalize_raw_capture(db, "run-schema")
    assert manifest is not None

    class UnsupportedSchemaRepository:
        async def aget_run_metadata(self, run_id: str):
            return await db.run_repository.aget_run_metadata(run_id)

        async def aget_raw_capture_manifest(self, run_id: str):
            loaded = await db.run_repository.aget_raw_capture_manifest(run_id)
            assert loaded is not None
            return replace(loaded, schema_version=loaded.schema_version + 1)

        async def aload_raw_capture_sensor_range(
            self,
            run_id: str,
            client_id: str,
            *,
            sample_start: int,
            sample_count: int,
        ):
            raise AssertionError("unsupported manifests must not read sidecar ranges")

    iterator = db.run_repository._run_sync(
        prepare_post_run_raw_window_iterator(UnsupportedSchemaRepository(), "run-schema")
    )

    assert iterator.plan is None
    assert "unsupported_schema_version" in {warning.code for warning in iterator.warnings}


def test_post_run_raw_window_iterator_validates_config() -> None:
    with pytest.raises(ValueError, match="0 <= overlap_pct < 1"):
        asyncio.run(
            prepare_post_run_raw_window_iterator(  # type: ignore[arg-type]
                object(),
                "run-invalid",
                config=PostRunRawWindowIteratorConfig(overlap_pct=1.0),
            )
        )
