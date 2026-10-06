"""Startup recovery of runs cut off before Stop (power lost, server killed).

The recording writes its sample rows to SQLite and its raw chunks to per-sensor
files as it goes; a recording checkpoint saves the run start and clock proof the
manifest needs. These tests leave a run ``recording`` the way a power cut does
and open the history again, as the next start does.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from test_support.history_db_lifecycle import create_recording_run

from vibesensor.history.history_db import INTERRUPTED_WITHOUT_DATA_ERROR, HistoryDB
from vibesensor.recording.raw_capture import RawCaptureChunk, RawCaptureSensorClockSync
from vibesensor.recording.sensor_frame_mapping import sensor_frame_from_mapping

_START = "2026-01-01T00:00:00+00:00"
_RUN_START_MONOTONIC_US = 5_000_000
_SYNC = RawCaptureSensorClockSync(
    clock_domain="server_monotonic",
    proof_state="verified",
    observed_monotonic_us=6_000_000,
    last_sync_monotonic_us=5_900_000,
    sync_offset_us=1_000,
    sync_rtt_us=2_000,
)


def _chunk(index: int, *, samples: int = 4) -> RawCaptureChunk:
    values = np.full((samples, 3), index, dtype=np.int16)
    return RawCaptureChunk(
        client_id="sensor-a",
        sample_rate_hz=800,
        t0_us=_RUN_START_MONOTONIC_US + index * 5_000,
        sample_count=samples,
        samples_i16le=values.tobytes(order="C"),
    )


def _record_until_the_power_cut(db_path: Path, run_id: str) -> None:
    """Record 13 sample rows and 4 raw chunks, then lose power mid-write; no Stop."""
    db = HistoryDB(db_path)
    create_recording_run(db, run_id, started_at=_START)
    db.append_samples(
        run_id,
        [sensor_frame_from_mapping({"t_s": 0.5 + 0.25 * i, "client_id": "a"}) for i in range(13)],
    )
    for index in range(3):
        db.append_raw_capture_chunk(run_id, _chunk(index))
    db.checkpoint_raw_capture(
        run_id,
        run_start_monotonic_us=_RUN_START_MONOTONIC_US,
        sensor_clock_sync={"sensor-a": _SYNC},
    )
    db.append_raw_capture_chunk(run_id, _chunk(3))
    db.close()
    # The power went while the next chunk was being written: half its samples
    # reached the data file and its index line stops mid-way.
    run_dir = db_path.parent / "raw-runs" / run_id
    with (run_dir / "sensor-a.raw.i16le").open("ab") as data:
        data.write(b"\x01" * 13)
    with (run_dir / "sensor-a.index.jsonl").open("ab") as index:
        index.write(b'{"sample_start":16,"sample_cou')


def test_a_run_cut_off_before_stop_is_recovered_for_analysis(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    _record_until_the_power_cut(db_path, "run-cut")

    db = HistoryDB(db_path)
    assert db.recover_interrupted_runs() == ["run-cut"]

    run = db.get_run("run-cut")
    assert run is not None
    assert run.status == "analyzing"
    assert run.error_message is None
    # Ended at its last saved sample (3.5 s in), on the clock its start was stamped on.
    last_sample = datetime(2026, 1, 1, 0, 0, 3, 500_000, tzinfo=UTC).isoformat()
    assert (run.end_time_utc, run.metadata.end_time_utc) == (last_sample, last_sample)
    assert run.metadata.interrupted
    assert db.stale_analyzing_run_ids() == ["run-cut"]
    assert db.list_runs()[0].interrupted

    # The torn chunk is cut off; the four whole ones replay with the checkpoint's anchors.
    manifest = run.raw_capture_manifest
    assert manifest is not None
    assert manifest.run_start_monotonic_us == _RUN_START_MONOTONIC_US
    sensor = manifest.sensor_manifest("sensor-a")
    assert sensor is not None
    assert (sensor.sample_count, sensor.chunk_count, sensor.bytes_written) == (16, 4, 96)
    assert sensor.clock_sync == _SYNC
    assert sensor.sample_rate_hz == 800
    capture = db.load_raw_capture("run-cut")
    assert capture is not None
    sensor_data = capture.sensor_data("sensor-a")
    assert sensor_data is not None
    assert sensor_data.samples_i16[:, 0].tolist() == [0] * 4 + [1] * 4 + [2] * 4 + [3] * 4
    assert sensor_data.chunks.sample_start.tolist() == [0, 4, 8, 12]

    # Recovery runs once: the next start finds nothing left recording.
    db.close()
    db = HistoryDB(db_path)
    assert db.recover_interrupted_runs() == []
    db.close()


def test_a_run_cut_off_before_any_sample_was_saved_is_an_error(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    db = HistoryDB(db_path)
    create_recording_run(db, "run-empty", started_at=_START)
    db.close()

    db = HistoryDB(db_path)
    assert db.recover_interrupted_runs() == []

    run = db.get_run("run-empty")
    assert run is not None
    assert run.status == "error"
    assert run.error_message == INTERRUPTED_WITHOUT_DATA_ERROR
    db.close()


def test_a_run_cut_off_after_its_raw_capture_was_finalized_keeps_that_manifest(
    tmp_path: Path,
) -> None:
    # Stop finalized the raw capture, then the power went before the run left recording.
    db_path = tmp_path / "history.db"
    db = HistoryDB(db_path)
    create_recording_run(db, "run-late", started_at=_START)
    db.append_samples("run-late", [sensor_frame_from_mapping({"t_s": 2.0, "client_id": "a"})])
    db.append_raw_capture_chunk("run-late", _chunk(0))
    finalized = db.finalize_raw_capture(
        "run-late",
        run_start_monotonic_us=_RUN_START_MONOTONIC_US,
        sensor_clock_sync={"sensor-a": _SYNC},
    )
    db.close()

    db = HistoryDB(db_path)
    assert db.recover_interrupted_runs() == ["run-late"]

    run = db.get_run("run-late")
    assert run is not None and run.status == "analyzing"
    assert run.raw_capture_manifest == finalized
    assert run.end_time_utc == datetime(2026, 1, 1, 0, 0, 2, tzinfo=UTC).isoformat()
    db.close()
