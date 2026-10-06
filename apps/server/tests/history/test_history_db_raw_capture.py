from __future__ import annotations

import io
import json
import shutil
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from test_support.history_db_lifecycle import (
    build_history_db,
    create_completed_run,
    create_recording_run,
)
from test_support.history_db_sql import execute_statements as _execute_statements

from vibesensor.history.exports import HistoryExportService
from vibesensor.history.history_db import HistoryDB
from vibesensor.recording.raw_capture import (
    RawCaptureChunk,
    RawCaptureLossStats,
    RawCaptureSensorClockSync,
)
from vibesensor.web.history_services import ProjectedHistoryExportService


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
    db.append_raw_capture_chunk(run_id, chunk)


def test_raw_capture_round_trip_persists_manifest_and_samples(
    db: HistoryDB,
) -> None:
    create_recording_run(db, "run-raw")
    first = np.asarray([[1, 2, 3], [4, 5, 6]], dtype=np.int16)
    second = np.asarray([[7, 8, 9]], dtype=np.int16)

    _append_chunk(db, run_id="run-raw", client_id="sensor-a", t0_us=1000, samples=first)
    _append_chunk(db, run_id="run-raw", client_id="sensor-a", t0_us=3500, samples=second)

    manifest = db.finalize_raw_capture(
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
    assert manifest.sensor_manifest("sensor-a").sample_rate_hz == 800
    assert manifest.sensor_manifest("sensor-a").declared_sample_rate_hz == 800
    assert manifest.sensor_manifest("sensor-a").sample_rate_proof_state == "observed_consistent"

    stored = db.get_run("run-raw")
    assert stored is not None
    assert stored.raw_capture_manifest == manifest

    loaded = db.load_raw_capture("run-raw")
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


def test_a_loaded_waveform_is_mapped_read_only_and_a_torn_index_line_is_skipped(
    tmp_path: Path, db: HistoryDB
) -> None:
    create_recording_run(db, "run-torn")
    first = np.asarray([[1, 2, 3], [4, 5, 6]], dtype=np.int16)
    second = np.asarray([[7, 8, 9]], dtype=np.int16)
    _append_chunk(db, run_id="run-torn", client_id="sensor-a", t0_us=1000, samples=first)
    _append_chunk(db, run_id="run-torn", client_id="sensor-a", t0_us=3500, samples=second)
    manifest = db.finalize_raw_capture("run-torn")
    assert manifest is not None
    sensor_manifest = manifest.sensor_manifest("sensor-a")
    assert sensor_manifest is not None
    # A power cut mid-write leaves half an index line behind.
    index_path = tmp_path / "raw-runs" / "run-torn" / sensor_manifest.index_file
    with index_path.open("a", encoding="utf-8") as handle:
        handle.write('{"sample_start": 3, "sample_co')

    loaded = db.load_raw_capture("run-torn")

    assert loaded is not None
    sensor = loaded.sensor_data("sensor-a")
    assert sensor is not None
    assert sensor.chunks.sample_start.tolist() == [0, 2]
    assert sensor.chunks.sample_count.tolist() == [2, 1]
    assert sensor.chunks.t0_us.tolist() == [1000, 3500]
    assert np.array_equal(sensor.samples_i16, np.vstack([first, second]))
    # Mapped from the file rather than copied into memory, and never written through.
    assert not sensor.samples_i16.flags.owndata
    assert not sensor.samples_i16.flags.writeable


def test_raw_capture_round_trip_persists_chunk_loss_counts_across_reload(
    tmp_path: Path, db: HistoryDB
) -> None:
    create_recording_run(db, "run-losses")
    samples = np.asarray([[1, 2, 3], [4, 5, 6]], dtype=np.int16)

    _append_chunk(db, run_id="run-losses", client_id="sensor-a", t0_us=1000, samples=samples)
    manifest = db.finalize_raw_capture(
        "run-losses",
        sensor_losses={
            "sensor-a": RawCaptureLossStats(
                udp_ingest_queue_drop_count=1,
                late_packet_chunk_count=1,
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
    assert manifest.total_late_packet_chunk_count == 1
    assert manifest.losses.udp_ingest_queue_drop_count == 1
    assert manifest.losses.late_packet_chunk_count == 1
    assert manifest.losses.queue_overflow_chunk_count == 2
    assert manifest.losses.invalid_chunk_count == 1
    assert manifest.losses.write_error_chunk_count == 1
    assert manifest.sensor_loss("sensor-a") is not None
    assert manifest.sensor_loss("sensor-a").losses.udp_ingest_queue_drop_count == 1
    assert manifest.sensor_loss("sensor-a").losses.late_packet_chunk_count == 1
    assert manifest.sensor_loss("sensor-a").losses.queue_overflow_chunk_count == 2
    assert manifest.sensor_loss("sensor-b") is not None
    assert manifest.sensor_loss("sensor-b").losses.write_error_chunk_count == 1

    db.close()
    reopened = build_history_db(tmp_path)
    stored = reopened.get_run("run-losses")

    assert stored is not None
    assert stored.raw_capture_manifest is not None
    assert stored.raw_capture_manifest.total_dropped_chunk_count == 5
    assert stored.raw_capture_manifest.total_late_packet_chunk_count == 1
    assert stored.raw_capture_manifest.losses.udp_ingest_queue_drop_count == 1
    assert stored.raw_capture_manifest.losses.late_packet_chunk_count == 1
    assert stored.raw_capture_manifest.losses.invalid_chunk_count == 1
    assert stored.raw_capture_manifest.sensor_loss("sensor-b") is not None
    assert stored.raw_capture_manifest.sensor_loss("sensor-b").losses.invalid_chunk_count == 1


def test_delete_run_removes_raw_capture_artifacts(tmp_path: Path, db: HistoryDB) -> None:
    create_recording_run(db, "run-delete")
    samples = np.asarray([[11, 12, 13]], dtype=np.int16)

    _append_chunk(db, run_id="run-delete", client_id="sensor-a", t0_us=1000, samples=samples)
    manifest = db.finalize_raw_capture("run-delete")

    assert manifest is not None
    raw_dir = tmp_path / "raw-runs" / "run-delete"
    assert raw_dir.exists()

    db.finalize_run("run-delete", "2026-01-01T00:01:00Z")
    db.store_analysis_error("run-delete", "failed")
    assert db.delete_run_if_safe("run-delete") == (True, None)

    assert not raw_dir.exists()


def test_missing_raw_capture_files_keep_run_summary_and_report_missing(
    tmp_path: Path,
    db: HistoryDB,
) -> None:
    create_completed_run(db, "run-raw-gone")
    samples = np.asarray([[11, 12, 13]], dtype=np.int16)

    _append_chunk(db, run_id="run-raw-gone", client_id="sensor-a", t0_us=1000, samples=samples)
    manifest = db.finalize_raw_capture("run-raw-gone")

    assert manifest is not None
    raw_dir = tmp_path / "raw-runs" / "run-raw-gone"
    shutil.rmtree(raw_dir)

    stored = db.get_run("run-raw-gone")
    assert stored is not None
    assert stored.raw_capture_manifest is not None
    assert stored.artifact_availability is not None
    assert stored.artifact_availability.raw_capture == "missing"
    assert db.load_raw_capture("run-raw-gone") is None


def test_raw_capture_finalization_persists_corrected_observed_sample_rate(
    db: HistoryDB,
) -> None:
    create_recording_run(db, "run-observed-rate")
    samples = np.asarray([[1, 2, 3]] * 8, dtype=np.int16)

    _append_chunk(
        db,
        run_id="run-observed-rate",
        client_id="sensor-a",
        t0_us=1_000_000,
        samples=samples,
        sample_rate_hz=800,
    )
    _append_chunk(
        db,
        run_id="run-observed-rate",
        client_id="sensor-a",
        t0_us=1_010_256,
        samples=samples,
        sample_rate_hz=800,
    )

    manifest = db.finalize_raw_capture("run-observed-rate")

    assert manifest is not None
    sensor_manifest = manifest.sensor_manifest("sensor-a")
    assert sensor_manifest is not None
    assert sensor_manifest.sample_rate_hz == 780
    assert sensor_manifest.declared_sample_rate_hz == 800
    assert sensor_manifest.sample_rate_proof_state == "observed_consistent"


def test_prune_terminal_runs_removes_raw_capture_artifacts(tmp_path: Path, db: HistoryDB) -> None:
    create_completed_run(db, "run-prune")
    samples = np.asarray([[21, 22, 23]], dtype=np.int16)

    _append_chunk(db, run_id="run-prune", client_id="sensor-a", t0_us=1000, samples=samples)
    manifest = db.finalize_raw_capture("run-prune")

    assert manifest is not None
    raw_dir = tmp_path / "raw-runs" / "run-prune"
    assert raw_dir.exists()

    old_timestamp = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    _execute_statements(
        db,
        (
            "UPDATE runs SET analysis_completed_at = ?, end_time_utc = ? WHERE run_id = ?",
            (old_timestamp, old_timestamp, "run-prune"),
        ),
    )

    db.prune_terminal_runs_older_than_days(1)

    assert not raw_dir.exists()


async def test_history_list_counts_raw_samples_and_export_carries_the_raw_capture(
    db: HistoryDB,
) -> None:
    create_recording_run(db, "run-export")
    create_recording_run(db, "run-no-raw", started_at="2026-01-02T00:00:00Z")
    sensor_a = np.asarray([[1, 2, 3], [4, 5, 6], [7, 8, 9]], dtype=np.int16)
    sensor_b = np.asarray([[-1, -2, -3], [-4, -5, -6]], dtype=np.int16)
    _append_chunk(db, run_id="run-export", client_id="sensor-a", t0_us=1000, samples=sensor_a)
    _append_chunk(db, run_id="run-export", client_id="sensor-b", t0_us=1000, samples=sensor_b)
    db.finalize_raw_capture("run-export")

    counts = {entry.run_id: entry.raw_sample_count for entry in db.list_runs()}
    assert counts == {"run-export": 5, "run-no-raw": None}

    export = await ProjectedHistoryExportService(HistoryExportService(db)).build_export(
        "run-export"
    )
    with zipfile.ZipFile(io.BytesIO(b"".join(export.iter_bytes()))) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("raw-capture/manifest.json"))
        raw_a = archive.read("raw-capture/sensor-a.raw.i16le")
        index_b = archive.read("raw-capture/sensor-b.index.jsonl").decode()

    assert names == {
        "run-export.json",
        "run-export_analysis_windows.csv",
        "raw-capture/manifest.json",
        "raw-capture/sensor-a.raw.i16le",
        "raw-capture/sensor-a.index.jsonl",
        "raw-capture/sensor-b.raw.i16le",
        "raw-capture/sensor-b.index.jsonl",
    }
    assert manifest["total_samples"] == 5
    assert np.array_equal(np.frombuffer(raw_a, dtype="<i2").reshape(-1, 3), sensor_a)
    assert json.loads(index_b)["sample_count"] == 2
