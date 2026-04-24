from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from test_support.history_db_async import execute_statements as _execute_statements
from test_support.history_db_lifecycle import (
    build_history_db,
    create_completed_run,
    create_recording_run,
)

from vibesensor.shared.types.raw_capture import (
    RawCaptureChunk,
    RawCaptureLossStats,
    RawCaptureSensorClockSync,
)


def _append_chunk(
    db,
    *,
    run_id: str,
    client_id: str,
    t0_us: int,
    samples: np.ndarray,
    sample_rate_hz: int = 800,
) -> None:
    chunk = RawCaptureChunk(
        client_id=client_id,
        sample_rate_hz=sample_rate_hz,
        t0_us=t0_us,
        sample_count=int(samples.shape[0]),
        samples_i16le=np.ascontiguousarray(samples, dtype=np.int16).tobytes(order="C"),
    )
    db.run_repository._run_sync(db.run_repository.aappend_raw_capture_chunk(run_id, chunk))


def _finalize_raw_capture(
    db,
    run_id: str,
    *,
    run_start_monotonic_us: int | None = None,
    sensor_clock_sync: dict[str, RawCaptureSensorClockSync] | None = None,
    sensor_losses: dict[str, RawCaptureLossStats] | None = None,
):
    return db.run_repository._run_sync(
        db.run_repository.afinalize_raw_capture(
            run_id,
            run_start_monotonic_us=run_start_monotonic_us,
            sensor_clock_sync=sensor_clock_sync,
            sensor_losses=sensor_losses,
        )
    )


def _load_raw_capture(db, run_id: str):
    return db.run_repository._run_sync(db.run_repository.aload_raw_capture(run_id))


def _load_raw_capture_range(
    db,
    *,
    run_id: str,
    client_id: str,
    sample_start: int,
    sample_count: int,
):
    return db.run_repository._run_sync(
        db.run_repository.aload_raw_capture_sensor_range(
            run_id,
            client_id,
            sample_start=sample_start,
            sample_count=sample_count,
        )
    )


def test_raw_capture_round_trip_persists_manifest_and_samples(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    create_recording_run(db, "run-raw")
    first = np.asarray([[1, 2, 3], [4, 5, 6]], dtype=np.int16)
    second = np.asarray([[7, 8, 9]], dtype=np.int16)

    _append_chunk(db, run_id="run-raw", client_id="sensor-a", t0_us=1000, samples=first)
    _append_chunk(db, run_id="run-raw", client_id="sensor-a", t0_us=2000, samples=second)

    manifest = _finalize_raw_capture(
        db,
        "run-raw",
        run_start_monotonic_us=1_234_567,
        sensor_clock_sync={
            "sensor-a": RawCaptureSensorClockSync(
                clock_domain="server_monotonic",
                proof_state="verified",
                observed_monotonic_us=1_300_000,
                last_sync_monotonic_us=1_299_000,
                sync_offset_us=5_000,
                sync_rtt_us=4_000,
            )
        },
    )

    assert manifest is not None
    assert manifest.total_samples == 3
    assert manifest.run_start_monotonic_us == 1_234_567
    assert manifest.sensor_manifest("sensor-a") is not None
    assert manifest.sensor_manifest("sensor-a").clock_sync is not None
    assert manifest.sensor_manifest("sensor-a").clock_sync.verified is True

    stored = db.run_repository.get_run("run-raw")
    assert stored is not None
    assert stored.raw_capture_manifest == manifest

    loaded = _load_raw_capture(db, "run-raw")
    assert loaded is not None
    assert loaded.manifest.run_start_monotonic_us == 1_234_567
    sensor = loaded.sensor_data("sensor-a")
    assert sensor is not None
    assert sensor.manifest.clock_sync is not None
    assert sensor.manifest.clock_sync.sync_rtt_us == 4_000
    assert sensor.manifest.chunk_count == 2
    assert sensor.manifest.sample_count == 3
    assert len(sensor.chunks) == 2
    assert np.array_equal(sensor.samples_i16, np.vstack([first, second]))


def test_raw_capture_round_trip_persists_chunk_loss_counts_across_reload(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    create_recording_run(db, "run-losses")
    samples = np.asarray([[1, 2, 3], [4, 5, 6]], dtype=np.int16)

    _append_chunk(db, run_id="run-losses", client_id="sensor-a", t0_us=1000, samples=samples)
    manifest = _finalize_raw_capture(
        db,
        "run-losses",
        sensor_losses={
            "sensor-a": RawCaptureLossStats(
                udp_ingest_queue_drop_count=1,
                queue_overflow_chunk_count=2,
            ),
            "sensor-b": RawCaptureLossStats(
                invalid_chunk_count=1,
                write_error_chunk_count=1,
            ),
        },
    )

    assert manifest is not None
    assert manifest.total_dropped_chunk_count == 5
    assert manifest.losses.udp_ingest_queue_drop_count == 1
    assert manifest.losses.queue_overflow_chunk_count == 2
    assert manifest.losses.invalid_chunk_count == 1
    assert manifest.losses.write_error_chunk_count == 1
    assert manifest.sensor_loss("sensor-a") is not None
    assert manifest.sensor_loss("sensor-a").losses.udp_ingest_queue_drop_count == 1
    assert manifest.sensor_loss("sensor-a").losses.queue_overflow_chunk_count == 2
    assert manifest.sensor_loss("sensor-b") is not None
    assert manifest.sensor_loss("sensor-b").losses.write_error_chunk_count == 1

    db.lifecycle.close()
    reopened = build_history_db(tmp_path)
    stored = reopened.run_repository.get_run("run-losses")

    assert stored is not None
    assert stored.raw_capture_manifest is not None
    assert stored.raw_capture_manifest.total_dropped_chunk_count == 5
    assert stored.raw_capture_manifest.losses.udp_ingest_queue_drop_count == 1
    assert stored.raw_capture_manifest.losses.invalid_chunk_count == 1
    assert stored.raw_capture_manifest.sensor_loss("sensor-b") is not None
    assert stored.raw_capture_manifest.sensor_loss("sensor-b").losses.invalid_chunk_count == 1


def test_delete_run_removes_raw_capture_artifacts(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    create_recording_run(db, "run-delete")
    samples = np.asarray([[11, 12, 13]], dtype=np.int16)

    _append_chunk(db, run_id="run-delete", client_id="sensor-a", t0_us=1000, samples=samples)
    manifest = _finalize_raw_capture(db, "run-delete")

    assert manifest is not None
    raw_dir = tmp_path / "raw-runs" / "run-delete"
    assert raw_dir.exists()

    db.run_repository.delete_run("run-delete")

    assert not raw_dir.exists()


def test_raw_capture_range_read_spans_chunk_boundaries_without_loading_full_capture(
    tmp_path: Path,
) -> None:
    db = build_history_db(tmp_path)
    create_recording_run(db, "run-range")
    first = np.asarray([[1, 2, 3], [4, 5, 6]], dtype=np.int16)
    second = np.asarray([[7, 8, 9], [10, 11, 12], [13, 14, 15]], dtype=np.int16)

    _append_chunk(db, run_id="run-range", client_id="sensor-a", t0_us=1000, samples=first)
    _append_chunk(db, run_id="run-range", client_id="sensor-a", t0_us=2000, samples=second)
    manifest = _finalize_raw_capture(db, "run-range")

    assert manifest is not None
    loaded = _load_raw_capture_range(
        db,
        run_id="run-range",
        client_id="sensor-a",
        sample_start=1,
        sample_count=3,
    )

    assert loaded is not None
    assert loaded.coverage_state == "full"
    assert loaded.returned_sample_start == 1
    assert loaded.returned_sample_count == 3
    assert len(loaded.chunks) == 2
    assert np.array_equal(loaded.samples_i16, np.vstack([first[1:], second[:2]]))


def test_raw_capture_range_read_marks_partial_and_missing_coverage(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    create_recording_run(db, "run-partial")
    samples = np.asarray([[1, 2, 3], [4, 5, 6], [7, 8, 9]], dtype=np.int16)

    _append_chunk(db, run_id="run-partial", client_id="sensor-a", t0_us=1000, samples=samples)
    manifest = _finalize_raw_capture(db, "run-partial")

    assert manifest is not None
    partial = _load_raw_capture_range(
        db,
        run_id="run-partial",
        client_id="sensor-a",
        sample_start=2,
        sample_count=3,
    )
    missing = _load_raw_capture_range(
        db,
        run_id="run-partial",
        client_id="sensor-b",
        sample_start=0,
        sample_count=2,
    )

    assert partial is not None
    assert partial.coverage_state == "partial"
    assert partial.returned_sample_start == 2
    assert partial.returned_sample_count == 1
    assert np.array_equal(partial.samples_i16, samples[2:])

    assert missing is not None
    assert missing.coverage_state == "missing"
    assert missing.returned_sample_start is None
    assert missing.returned_sample_count == 0


def test_prune_terminal_runs_removes_raw_capture_artifacts(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    create_completed_run(db, "run-prune")
    samples = np.asarray([[21, 22, 23]], dtype=np.int16)

    _append_chunk(db, run_id="run-prune", client_id="sensor-a", t0_us=1000, samples=samples)
    manifest = _finalize_raw_capture(db, "run-prune")

    assert manifest is not None
    raw_dir = tmp_path / "raw-runs" / "run-prune"
    assert raw_dir.exists()

    old_timestamp = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    _execute_statements(
        db.lifecycle,
        (
            "UPDATE runs SET analysis_completed_at = ?, end_time_utc = ? WHERE run_id = ?",
            (old_timestamp, old_timestamp, "run-prune"),
        ),
    )

    db.run_repository.prune_terminal_runs_older_than_days(1)

    assert not raw_dir.exists()
