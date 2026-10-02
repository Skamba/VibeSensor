"""Structured sample-storage and v2 row retrieval coverage for HistoryDB."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from test_support.history_db_lifecycle import create_recording_run, run_samples
from test_support.history_db_lifecycle import make_analysis_summary as _analysis
from test_support.history_db_sql import execute_statements, fetch_all, fetch_one
from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.adapters.persistence.history_db._history_db import HistoryDB
from vibesensor.recording.sensor_frame_mapping import (
    sensor_frame_from_mapping,
    sensor_frame_to_json_object,
)


def _sensor_frame_dict(i: int, *, run_id: str = "run-v2") -> dict[str, object]:
    return {
        "record_type": "sample",
        "schema_version": "v2-jsonl",
        "run_id": run_id,
        "timestamp_utc": f"2026-01-01T00:00:{i:02d}Z",
        "t_s": float(i),
        "client_id": "aabbccddeeff",
        "client_name": "front-left",
        "location": "front_left",
        "sample_rate_hz": 800,
        "speed_kmh": 60.0 + i,
        "gps_speed_kmh": 59.5 + i,
        "speed_source": "gps",
        "engine_rpm": 3200.0,
        "engine_rpm_source": "obd2",
        "gear": 4.0,
        "final_drive_ratio": 3.08,
        "accel_x_g": 0.02 + i * 0.001,
        "accel_y_g": 0.03,
        "accel_z_g": 0.04,
        "dominant_freq_hz": 15.0,
        "dominant_axis": "x",
        "vibration_strength_db": 22.0,
        "strength_bucket": "l2",
        "strength_peak_amp_g": 0.12,
        "strength_floor_amp_g": 0.005,
        "frames_dropped_total": 0,
        "queue_overflow_drops": 0,
        "top_peaks": [
            {"hz": 15.0, "amp": 0.12, "vibration_strength_db": 22.0, "strength_bucket": "l2"},
        ],
    }


def test_v2_structured_roundtrip(db: HistoryDB) -> None:
    create_recording_run(db, "run-v2")
    originals = [_sensor_frame_dict(i) for i in range(5)]
    db.append_samples("run-v2", [sensor_frame_from_mapping(sample) for sample in originals])

    retrieved = run_samples(db, "run-v2")
    assert len(retrieved) == 5
    for i, row in enumerate(retrieved):
        orig = originals[i]
        assert row.t_s == orig["t_s"]
        assert row.client_id == orig["client_id"]
        assert row.speed_kmh == orig["speed_kmh"]
        assert row.accel_x_g == pytest.approx(orig["accel_x_g"])
        assert row.vibration_strength_db == orig["vibration_strength_db"]
        assert sensor_frame_to_json_object(row)["top_peaks"] == orig["top_peaks"]


def test_v2_nan_inf_sanitized(db: HistoryDB) -> None:
    create_recording_run(db, "run-nan")
    sample = {
        "speed_kmh": float("nan"),
        "gps_speed_kmh": float("-inf"),
        "engine_rpm": float("inf"),
        "accel_x_g": float("inf"),
        "vibration_strength_db": float("nan"),
        "strength_peak_amp_g": float("inf"),
        "t_s": 1.0,
        "client_id": "nan-client",
        "strength_bucket": "l2",
    }
    db.append_samples("run-nan", [sensor_frame_from_mapping(sample)])

    stored = fetch_one(
        db,
        """
        SELECT speed_kmh, gps_speed_kmh, engine_rpm, accel_x_g,
               vibration_strength_db, strength_peak_amp_g, t_s, client_id, strength_bucket
        FROM samples_v2 WHERE run_id = ?
        """,
        ("run-nan",),
    )
    assert stored == (None, None, None, None, None, None, 1.0, "nan-client", "l2")

    rows = run_samples(db, "run-nan")
    assert len(rows) == 1
    assert rows[0].speed_kmh is None
    assert rows[0].gps_speed_kmh is None
    assert rows[0].engine_rpm is None
    assert rows[0].accel_x_g is None
    assert rows[0].vibration_strength_db is None
    assert rows[0].strength_peak_amp_g is None
    assert rows[0].t_s == 1.0
    assert rows[0].client_id == "nan-client"
    assert rows[0].strength_bucket == "l2"


def test_v2_no_json_blobs_in_storage(db: HistoryDB) -> None:
    create_recording_run(db, "run-check")
    db.append_samples("run-check", [sensor_frame_from_mapping(_sensor_frame_dict(0))])

    columns = {row[1] for row in fetch_all(db, "PRAGMA table_info(samples_v2)")}

    assert "sample_json" not in columns
    assert "accel_x_g" in columns
    assert "speed_kmh" in columns
    assert "vibration_strength_db" in columns
    assert "top_peaks" in columns


def test_v4_db_rejected(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA user_version = 4")
    conn.executescript("""\
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'recording',
            start_time_utc TEXT NOT NULL,
            end_time_utc TEXT,
            metadata_json TEXT NOT NULL,
            analysis_json TEXT,
            error_message TEXT,
            sample_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            analysis_version INTEGER,
            analysis_started_at TEXT,
            analysis_completed_at TEXT
        );

        CREATE TABLE samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            sample_json TEXT NOT NULL
        );
        CREATE INDEX idx_samples_run_id ON samples(run_id);

        CREATE TABLE settings_kv (
            key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE client_names (
            client_id TEXT PRIMARY KEY, name TEXT NOT NULL, updated_at TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()

    # No migrations are registered — opening a v4 database raises RuntimeError.
    with pytest.raises(RuntimeError, match="incompatible"):
        HistoryDB(db_path)


def test_v2_sensor_frame_objects(db: HistoryDB) -> None:
    create_recording_run(db, "run-sf")

    frame = sensor_frame_from_mapping(_sensor_frame_dict(0, run_id="run-sf"))
    db.append_samples("run-sf", [frame])

    rows = run_samples(db, "run-sf")
    assert len(rows) == 1
    assert rows[0].client_id == "aabbccddeeff"
    assert rows[0].speed_kmh == 60.0
    assert rows[0].top_peaks == frame.top_peaks


def test_v2_delete_cascades_legacy_and_v2(db: HistoryDB) -> None:
    create_recording_run(db, "run-del2")
    db.append_samples(
        "run-del2",
        [sensor_frame_from_mapping(_sensor_frame_dict(i, run_id="run-del2")) for i in range(3)],
    )

    assert len(run_samples(db, "run-del2")) == 3
    db.finalize_run("run-del2", "2026-01-01T00:01:00Z")
    db.store_analysis_error("run-del2", "failed")
    assert db.delete_run_if_safe("run-del2") == (True, None)

    row = fetch_one(db, "SELECT COUNT(*) FROM samples_v2 WHERE run_id = ?", ("run-del2",))
    assert row is not None and row[0] == 0


def test_v2_record_then_export_roundtrip(db: HistoryDB) -> None:
    create_recording_run(db, "run-full", source="roundtrip")

    for batch_start in range(0, 20, 5):
        batch = [
            _sensor_frame_dict(i, run_id="run-full") for i in range(batch_start, batch_start + 5)
        ]
        db.append_samples("run-full", [sensor_frame_from_mapping(sample) for sample in batch])

    db.finalize_run("run-full", "2026-01-01T00:00:20Z")
    assert db.get_run("run-full").status.value == "analyzing"

    analysis = _analysis("run-full", score=42)
    db.store_analysis("run-full", make_persisted_analysis(analysis))
    assert db.get_run("run-full").status.value == "complete"

    all_samples = run_samples(db, "run-full")
    assert len(all_samples) == 20

    batched = list(db.iter_run_samples("run-full", batch_size=7))
    flat = [s for b in batched for s in b]
    assert len(flat) == 20
    assert [s.t_s for s in flat] == [float(i) for i in range(20)]

    run = db.get_run("run-full")
    assert run is not None
    assert run.sample_count == 20
    assert run.status.value == "complete"
    assert db.get_run("run-full").analysis == analysis


def test_iter_run_samples_skips_corrupt_rows_and_continues(db: HistoryDB) -> None:
    create_recording_run(db, "run-corrupt")
    db.append_samples(
        "run-corrupt",
        [sensor_frame_from_mapping({"t_s": 1.0}), sensor_frame_from_mapping({"t_s": 2.0})],
    )
    execute_statements(
        db,
        ("INSERT INTO samples_v2 (run_id, top_peaks) VALUES (?, ?)", ("run-corrupt", "{bad")),
    )
    db.append_samples("run-corrupt", [sensor_frame_from_mapping({"t_s": 3.0})])

    rows = [
        sample for batch in db.iter_run_samples("run-corrupt", batch_size=2) for sample in batch
    ]
    assert len(rows) == 3
    assert rows[0].t_s == 1.0
    assert rows[1].t_s == 2.0
    assert rows[2].t_s == 3.0


def test_v2_row_to_dict_non_list_peak_column_warns_and_skips_row(
    db: HistoryDB,
    caplog: pytest.LogCaptureFixture,
) -> None:
    create_recording_run(db, "run-peak-warn")

    execute_statements(
        db,
        (
            "INSERT INTO samples_v2 (run_id, top_peaks) VALUES (?, ?)",
            ("run-peak-warn", '{"unexpected": "dict"}'),
        ),
    )

    import logging

    with caplog.at_level(logging.WARNING, logger="vibesensor.adapters.persistence.history_db"):
        rows = run_samples(db, "run-peak-warn")

    assert rows == []
    assert "top_peaks" in caplog.text
