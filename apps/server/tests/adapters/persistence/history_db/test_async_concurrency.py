"""Concurrency and cancellation coverage for the async history-DB surface.

Exercises the aiosqlite-backed ``RunPersistence`` port directly via its ``a*``
methods to verify:

* concurrent reads and writes under ``asyncio.gather`` converge to a consistent
  committed state;
* cancellation of an in-flight ``aappend_samples`` leaves the database usable
  and a follow-up append still writes;
* calling ``aclose`` with an outstanding task cancels/settles cleanly and
  further operations raise (engine closed).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames.mapping import sensor_frame_from_mapping
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame


def _metadata(run_id: str) -> RunMetadata:
    return run_metadata_from_mapping(
        {
            "run_id": run_id,
            "start_time_utc": "2026-01-01T00:00:00Z",
            "sensor_model": "ADXL345",
            "raw_sample_rate_hz": 800,
            "sample_rate_hz": 800,
            "feature_interval_s": 1.0,
            "source": "test",
        }
    )


def _frame(run_id: str, seq: int) -> SensorFrame:
    return sensor_frame_from_mapping(
        {
            "run_id": run_id,
            "timestamp_utc": "2026-01-01T00:00:00Z",
            "t_s": 1.0 + seq * 0.01,
            "client_id": "client-1",
            "client_name": "front",
            "location": "front",
            "sample_rate_hz": 800,
            "speed_kmh": 0.0,
            "gps_speed_kmh": 0.0,
            "speed_source": "gps",
            "engine_rpm": 0.0,
            "engine_rpm_source": "none",
            "gear": None,
            "final_drive_ratio": None,
            "accel_x_g": 0.0,
            "accel_y_g": 0.0,
            "accel_z_g": 1.0,
            "dominant_freq_hz": 0.0,
            "dominant_axis": "z",
            "top_peaks": [],
            "vibration_strength_db": 0.0,
            "strength_bucket": "low",
            "strength_peak_amp_g": 0.0,
            "strength_floor_amp_g": 0.0,
            "frames_dropped_total": 0,
            "queue_overflow_drops": 0,
        }
    )


def _frames(run_id: str, n: int, *, start: int = 0) -> list[SensorFrame]:
    return [_frame(run_id, start + i) for i in range(n)]


@pytest.mark.asyncio
async def test_concurrent_reads_and_writes_converge(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    try:
        run_id = "run-concurrent"
        repo = db.run_repository
        await repo.acreate_run(run_id, "2026-01-01T00:00:00Z", _metadata(run_id))

        async def append_chunk(offset: int) -> int:
            return await repo.aappend_samples(run_id, _frames(run_id, 20, start=offset))

        async def read_list() -> int:
            entries = await repo.alist_runs()
            return len(entries)

        results = await asyncio.gather(
            append_chunk(0),
            append_chunk(20),
            append_chunk(40),
            read_list(),
            read_list(),
        )

        appended = list(results[:3])
        assert sum(appended) == 60

        samples = await repo.aget_run_samples(run_id)
        assert len(samples) == 60
    finally:
        await db.aclose()


@pytest.mark.asyncio
async def test_cancellation_of_in_flight_append_keeps_db_usable(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    try:
        run_id = "run-cancel"
        repo = db.run_repository
        await repo.acreate_run(run_id, "2026-01-01T00:00:00Z", _metadata(run_id))

        write_lock_held = asyncio.Event()
        release_write_lock = asyncio.Event()

        async def hold_write_lock() -> None:
            async with db.lifecycle.write_transaction_cursor():
                write_lock_held.set()
                await release_write_lock.wait()

        blocker = asyncio.create_task(hold_write_lock())
        await write_lock_held.wait()
        try:
            task = asyncio.create_task(repo.aappend_samples(run_id, _frames(run_id, 200)))
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release_write_lock.set()
            await blocker

        written = await repo.aappend_samples(run_id, _frames(run_id, 5, start=1000))
        assert written == 5
        samples = await repo.aget_run_samples(run_id)
        assert len(samples) >= 5
    finally:
        await db.aclose()


@pytest.mark.asyncio
async def test_aclose_during_outstanding_task_settles(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    run_id = "run-shutdown"
    repo = db.run_repository
    await repo.acreate_run(run_id, "2026-01-01T00:00:00Z", _metadata(run_id))

    task = asyncio.create_task(repo.aappend_samples(run_id, _frames(run_id, 50)))
    await asyncio.sleep(0)
    await db.aclose()

    try:
        await task
    except BaseException:
        pass

    with pytest.raises(RuntimeError):
        await repo.aappend_samples(run_id, _frames(run_id, 1))
