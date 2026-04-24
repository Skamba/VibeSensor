"""Focused schema-migration matrix coverage for HistoryDB."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from test_support.history_db_async import fetch_all as _fetch_all
from test_support.history_db_async import fetch_one as _fetch_one
from test_support.history_db_lifecycle import (
    make_analysis_summary as _analysis,
)
from test_support.history_db_lifecycle import (
    make_run_metadata as _metadata,
)
from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
from vibesensor.adapters.persistence.history_db._schema import SCHEMA_VERSION
from vibesensor.shared.boundaries.analysis_payloads import (
    persisted_analysis_to_storage_json_object,
)
from vibesensor.shared.boundaries.runs.metadata import run_metadata_to_json_object
from vibesensor.shared.boundaries.sensor_frames import (
    SENSOR_FRAME_FIELD_NAMES,
    sensor_frame_from_mapping,
    sensor_frame_to_row_values,
)
from vibesensor.shared.types.raw_capture import (
    RawCaptureManifest,
    RawCaptureSensorManifest,
)
from vibesensor.shared.types.whole_run_analysis import (
    WholeRunArtifactFile,
    WholeRunArtifactManifest,
    WholeRunWindowPolicy,
)

_RUN_ID = "run-legacy"
_LEGACY_RUN_BASE_COLUMNS: tuple[str, ...] = (
    "run_id",
    "case_id",
    "status",
    "start_time_utc",
    "end_time_utc",
    "metadata_json",
    "analysis_json",
    "error_message",
    "sample_count",
    "created_at",
    "analysis_started_at",
    "analysis_completed_at",
)
_OPTIONAL_RUN_COLUMNS_BY_VERSION: dict[int, tuple[str, ...]] = {
    12: ("car_name",),
    13: ("car_name", "raw_capture_manifest_json"),
    14: ("car_name", "raw_capture_manifest_json", "whole_run_artifact_manifest_json"),
}
_ANALYSIS_WINDOW_COLUMNS = {
    "analysis_window_start_us",
    "analysis_window_end_us",
    "analysis_window_synced",
}
_LEGACY_SAMPLE_COLUMNS: tuple[str, ...] = tuple(
    name for name in SENSOR_FRAME_FIELD_NAMES if name not in _ANALYSIS_WINDOW_COLUMNS
)


def _create_runs_schema(version: int) -> str:
    columns = [
        "run_id                  TEXT PRIMARY KEY",
        "case_id                 TEXT",
        "status                  TEXT NOT NULL DEFAULT 'recording'"
        " CHECK (status IN ('recording', 'analyzing', 'complete', 'error'))",
        "start_time_utc          TEXT NOT NULL",
        "end_time_utc            TEXT",
        "metadata_json           TEXT NOT NULL",
    ]
    if version >= 12:
        columns.append("car_name                TEXT")
    if version >= 13:
        columns.append("raw_capture_manifest_json TEXT")
    if version >= 14:
        columns.append("whole_run_artifact_manifest_json TEXT")
    columns.extend(
        (
            "analysis_json           TEXT",
            "error_message           TEXT",
            "sample_count            INTEGER NOT NULL DEFAULT 0",
            "created_at              TEXT NOT NULL",
            "analysis_started_at     TEXT",
            "analysis_completed_at   TEXT",
        )
    )
    return "CREATE TABLE runs (\n    " + ",\n    ".join(columns) + "\n);"


def _create_samples_schema() -> str:
    columns = [
        "id                    INTEGER PRIMARY KEY AUTOINCREMENT",
        "run_id                TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE",
        "timestamp_utc         TEXT",
        "t_s                   REAL",
        "client_id             TEXT",
        "client_name           TEXT",
        "location              TEXT",
        "sample_rate_hz        INTEGER",
        "speed_kmh             REAL",
        "gps_speed_kmh         REAL",
        "speed_source          TEXT",
        "engine_rpm            REAL",
        "engine_rpm_source     TEXT",
        "gear                  REAL",
        "final_drive_ratio     REAL",
        "accel_x_g             REAL",
        "accel_y_g             REAL",
        "accel_z_g             REAL",
        "dominant_freq_hz      REAL",
        "dominant_axis         TEXT",
        "vibration_strength_db REAL",
        "strength_bucket       TEXT",
        "strength_peak_amp_g   REAL",
        "strength_floor_amp_g  REAL",
        "frames_dropped_total  INTEGER DEFAULT 0",
        "queue_overflow_drops  INTEGER DEFAULT 0",
        "top_peaks             TEXT",
    ]
    return "CREATE TABLE samples_v2 (\n    " + ",\n    ".join(columns) + "\n);"


def _legacy_run_columns(version: int) -> tuple[str, ...]:
    return (
        _LEGACY_RUN_BASE_COLUMNS[:6]
        + _OPTIONAL_RUN_COLUMNS_BY_VERSION.get(version, ())
        + _LEGACY_RUN_BASE_COLUMNS[6:]
    )


def _analysis_json() -> str:
    analysis = make_persisted_analysis(_analysis(_RUN_ID))
    return json.dumps(persisted_analysis_to_storage_json_object(analysis))


def _raw_capture_manifest_json() -> str:
    manifest = RawCaptureManifest(
        run_id=_RUN_ID,
        relative_dir="raw/legacy-run",
        sensors=(
            RawCaptureSensorManifest(
                client_id="sensor-a",
                sample_rate_hz=800,
                data_file="sensor-a.bin",
                index_file="sensor-a.idx.jsonl",
                sample_count=2,
                chunk_count=1,
                bytes_written=24,
                first_t0_us=500_000,
                last_t0_us=501_250,
            ),
        ),
        total_samples=2,
        total_bytes=24,
        created_at="2026-01-01T00:00:02Z",
        run_start_monotonic_us=500_000,
    )
    return json.dumps(manifest.to_json_object())


def _whole_run_manifest_json() -> str:
    manifest = WholeRunArtifactManifest(
        run_id=_RUN_ID,
        relative_dir="whole-run/legacy-run",
        window_policy=WholeRunWindowPolicy(
            sample_rate_hz=800,
            window_size_samples=800,
            stride_samples=800,
            overlap_samples=0,
            feature_interval_s=1.0,
        ),
        total_window_count=1,
        artifacts=(
            WholeRunArtifactFile(
                artifact_key="spectrum",
                relative_path="spectrum.jsonl",
                file_format="jsonl",
                record_count=1,
                sensor_id="sensor-a",
            ),
        ),
        created_at="2026-01-01T00:00:03Z",
    )
    return json.dumps(manifest.to_json_object())


def _seed_run_values(version: int) -> tuple[object, ...]:
    metadata_json = json.dumps(
        run_metadata_to_json_object(
            _metadata(
                _RUN_ID,
                active_car_snapshot={"name": "Legacy Car"},
                fft_window_size_samples=800,
            )
        )
    )
    values_by_column: dict[str, object] = {
        "run_id": _RUN_ID,
        "case_id": "case-legacy",
        "status": "complete",
        "start_time_utc": "2026-01-01T00:00:00Z",
        "end_time_utc": "2026-01-01T00:00:02Z",
        "metadata_json": metadata_json,
        "car_name": "Legacy Car",
        "raw_capture_manifest_json": _raw_capture_manifest_json(),
        "whole_run_artifact_manifest_json": _whole_run_manifest_json(),
        "analysis_json": _analysis_json(),
        "error_message": None,
        "sample_count": 2,
        "created_at": "2026-01-01T00:00:01Z",
        "analysis_started_at": "2026-01-01T00:00:02Z",
        "analysis_completed_at": "2026-01-01T00:00:03Z",
    }
    return tuple(values_by_column[column] for column in _legacy_run_columns(version))


def _seed_sample_values(
    *,
    t_s: float,
    timestamp_utc: str,
    dominant_freq_hz: float,
) -> tuple[object, ...]:
    frame = sensor_frame_from_mapping(
        {
            "run_id": _RUN_ID,
            "timestamp_utc": timestamp_utc,
            "t_s": t_s,
            "client_id": "sensor-a",
            "client_name": "Front Left",
            "location": "front-left",
            "sample_rate_hz": 800,
            "speed_kmh": 54.0,
            "gps_speed_kmh": 53.5,
            "speed_source": "gps",
            "engine_rpm": 2200.0,
            "engine_rpm_source": "obd",
            "gear": 3.0,
            "final_drive_ratio": 4.1,
            "accel_x_g": 0.18,
            "accel_y_g": 0.02,
            "accel_z_g": 0.05,
            "dominant_freq_hz": dominant_freq_hz,
            "dominant_axis": "x",
            "vibration_strength_db": 15.5,
            "strength_bucket": "moderate",
            "strength_peak_amp_g": 0.92,
            "strength_floor_amp_g": 0.15,
            "frames_dropped_total": 0,
            "queue_overflow_drops": 0,
            "top_peaks": [],
        }
    )
    row_by_column = dict(
        zip(
            SENSOR_FRAME_FIELD_NAMES,
            sensor_frame_to_row_values(frame),
            strict=True,
        )
    )
    return tuple(row_by_column[column] for column in _LEGACY_SAMPLE_COLUMNS)


def _seed_legacy_history_db(db_path: Path, *, version: int) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(_create_runs_schema(version))
        conn.executescript(_create_samples_schema())
        run_columns = _legacy_run_columns(version)
        conn.execute(
            f"INSERT INTO runs ({', '.join(run_columns)}) "
            f"VALUES ({', '.join('?' for _ in run_columns)})",
            _seed_run_values(version),
        )
        conn.executemany(
            f"INSERT INTO samples_v2 ({', '.join(_LEGACY_SAMPLE_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in _LEGACY_SAMPLE_COLUMNS)})",
            (
                _seed_sample_values(
                    t_s=0.0,
                    timestamp_utc="2026-01-01T00:00:00Z",
                    dominant_freq_hz=31.5,
                ),
                _seed_sample_values(
                    t_s=1.0,
                    timestamp_utc="2026-01-01T00:00:01Z",
                    dominant_freq_hz=47.0,
                ),
            ),
        )
        conn.execute(f"PRAGMA user_version = {version}")
        conn.commit()
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("version", "expect_raw_manifest", "expect_whole_manifest"),
    [
        (11, False, False),
        (12, False, False),
        (13, True, False),
        (14, True, True),
    ],
)
def test_supported_legacy_versions_migrate_seeded_history_data(
    tmp_path: Path,
    *,
    version: int,
    expect_raw_manifest: bool,
    expect_whole_manifest: bool,
) -> None:
    db_path = tmp_path / f"history-v{version}.db"
    _seed_legacy_history_db(db_path, version=version)

    db = create_history_persistence_adapters(db_path)
    try:
        listed_run = db.run_repository.list_runs()[0]
        stored_run = db.run_repository.get_run(_RUN_ID)
        assert stored_run is not None

        version_row = _fetch_one(db.lifecycle, "PRAGMA user_version")
        run_columns = {str(row[1]) for row in _fetch_all(db.lifecycle, "PRAGMA table_info(runs)")}
        sample_columns = {
            str(row[1]) for row in _fetch_all(db.lifecycle, "PRAGMA table_info(samples_v2)")
        }
        samples = db.run_repository.get_run_samples(_RUN_ID)

        assert version_row == (SCHEMA_VERSION,)
        assert {
            "car_name",
            "raw_capture_manifest_json",
            "whole_run_artifact_manifest_json",
        } <= run_columns
        assert _ANALYSIS_WINDOW_COLUMNS <= sample_columns

        assert listed_run.run_id == _RUN_ID
        assert listed_run.car_name == "Legacy Car"
        assert listed_run.sample_count == 2

        assert stored_run.metadata.run_id == _RUN_ID
        assert stored_run.metadata.raw_sample_rate_hz == 800
        assert stored_run.analysis is not None
        assert stored_run.analysis["run_id"] == _RUN_ID
        assert (stored_run.raw_capture_manifest is not None) is expect_raw_manifest
        assert (stored_run.whole_run_artifact_manifest is not None) is expect_whole_manifest
        if stored_run.raw_capture_manifest is not None:
            sensor_manifest = stored_run.raw_capture_manifest.sensor_manifest("sensor-a")
            assert sensor_manifest is not None
            assert sensor_manifest.first_t0_us == 500_000
        if stored_run.whole_run_artifact_manifest is not None:
            assert stored_run.whole_run_artifact_manifest.artifact("spectrum") is not None

        assert [sample.dominant_freq_hz for sample in samples] == [31.5, 47.0]
        assert all(sample.client_id == "sensor-a" for sample in samples)
        assert all(sample.analysis_window_start_us is None for sample in samples)
        assert all(sample.analysis_window_end_us is None for sample in samples)
        assert all(sample.analysis_window_synced is None for sample in samples)
        assert db.run_repository.verify_run_integrity(_RUN_ID) == []
    finally:
        db.lifecycle.close()


def test_legacy_schema_meta_table_fails_fast_with_clear_guidance(tmp_path: Path) -> None:
    db_path = tmp_path / "history-schema-meta.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE schema_meta (schema_version INTEGER NOT NULL)")
        conn.execute("INSERT INTO schema_meta (schema_version) VALUES (7)")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(RuntimeError, match="legacy schema_meta table incompatible"):
        create_history_persistence_adapters(db_path)
