from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from vibesensor.history_db import HistoryDB


def _sensor_frame_dict(i: int, *, run_id: str = "run-v2") -> dict:
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
        "top_peaks_x": [{"hz": 15.0, "amp": 0.12}],
        "top_peaks_y": [{"hz": 16.0, "amp": 0.08}],
        "top_peaks_z": [],
    }


def test_v2_structured_roundtrip(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-v2", "2026-01-01T00:00:00Z", {"source": "test"})
    originals = [_sensor_frame_dict(i) for i in range(5)]
    db.append_samples("run-v2", originals)

    retrieved = db.get_run_samples("run-v2")
    assert len(retrieved) == 5
    for i, row in enumerate(retrieved):
        orig = originals[i]
        assert row["t_s"] == orig["t_s"]
        assert row["client_id"] == orig["client_id"]
        assert row["speed_kmh"] == orig["speed_kmh"]
        assert row["accel_x_g"] == pytest.approx(orig["accel_x_g"])
        assert row["vibration_strength_db"] == orig["vibration_strength_db"]
        assert row["top_peaks"] == orig["top_peaks"]
        assert row["top_peaks_x"] == orig["top_peaks_x"]
        assert row["top_peaks_y"] == orig["top_peaks_y"]
        assert row["top_peaks_z"] == orig["top_peaks_z"]


def test_v2_extra_keys_preserved(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-extra", "2026-01-01T00:00:00Z", {"source": "test"})
    sample = {"custom_key": "hello", "nested": {"a": 1}, "i": 42}
    db.append_samples("run-extra", [sample])

    rows = db.get_run_samples("run-extra")
    assert len(rows) == 1
    assert rows[0]["custom_key"] == "hello"
    assert rows[0]["nested"] == {"a": 1}
    assert rows[0]["i"] == 42


def test_v2_nan_inf_sanitized(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-nan", "2026-01-01T00:00:00Z", {"source": "test"})
    sample = {"speed_kmh": float("nan"), "accel_x_g": float("inf"), "t_s": 1.0}
    db.append_samples("run-nan", [sample])

    rows = db.get_run_samples("run-nan")
    assert len(rows) == 1
    assert rows[0]["speed_kmh"] is None
    assert rows[0]["accel_x_g"] is None
    assert rows[0]["t_s"] == 1.0


def test_v2_no_json_blobs_in_storage(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-check", "2026-01-01T00:00:00Z", {"source": "test"})
    db.append_samples("run-check", [_sensor_frame_dict(0)])

    with db._cursor(commit=False) as cur:
        cur.execute("PRAGMA table_info(samples_v2)")
        columns = {row[1] for row in cur.fetchall()}

    assert "sample_json" not in columns
    assert "accel_x_g" in columns
    assert "speed_kmh" in columns
    assert "vibration_strength_db" in columns
    assert "top_peaks" in columns


def test_v4_db_rejected(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""\
        CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO schema_meta (key, value) VALUES ('version', '4');

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

    # v4→v5 migration is now supported — DB should open successfully.
    db = HistoryDB(db_path)
    # Verify it migrated to current version.
    with db._cursor(commit=False) as cur:
        cur.execute("SELECT value FROM schema_meta WHERE key = 'version'")
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "5"
    db.close()


def test_v2_sensor_frame_objects(tmp_path: Path) -> None:
    from vibesensor.domain_models import SensorFrame

    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-sf", "2026-01-01T00:00:00Z", {"source": "test"})

    frame = SensorFrame.from_dict(_sensor_frame_dict(0, run_id="run-sf"))
    db.append_samples("run-sf", [frame])

    rows = db.get_run_samples("run-sf")
    assert len(rows) == 1
    assert rows[0]["client_id"] == "aabbccddeeff"
    assert rows[0]["speed_kmh"] == 60.0
    assert rows[0]["top_peaks"] == frame.top_peaks


def test_v2_delete_cascades_legacy_and_v2(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-del2", "2026-01-01T00:00:00Z", {"source": "test"})
    db.append_samples("run-del2", [_sensor_frame_dict(i, run_id="run-del2") for i in range(3)])

    assert len(db.get_run_samples("run-del2")) == 3
    db.delete_run("run-del2")

    with db._cursor(commit=False) as cur:
        cur.execute("SELECT COUNT(*) FROM samples_v2 WHERE run_id = ?", ("run-del2",))
        assert cur.fetchone()[0] == 0


def test_v2_record_then_export_roundtrip(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-full", "2026-01-01T00:00:00Z", {"source": "roundtrip"})

    for batch_start in range(0, 20, 5):
        batch = [
            _sensor_frame_dict(i, run_id="run-full") for i in range(batch_start, batch_start + 5)
        ]
        db.append_samples("run-full", batch)

    db.finalize_run("run-full", "2026-01-01T00:00:20Z")
    assert db.get_run_status("run-full") == "analyzing"

    db.store_analysis("run-full", {"score": 42})
    assert db.get_run_status("run-full") == "complete"

    all_samples = db.get_run_samples("run-full")
    assert len(all_samples) == 20

    batched = list(db.iter_run_samples("run-full", batch_size=7))
    flat = [s for b in batched for s in b]
    assert len(flat) == 20
    assert [s["t_s"] for s in flat] == [float(i) for i in range(20)]

    run = db.get_run("run-full")
    assert run is not None
    assert run["sample_count"] == 20
    assert run["status"] == "complete"
    analysis = db.get_run_analysis("run-full")
    assert analysis is not None
    assert analysis["score"] == 42


def test_v2_iter_with_offset(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-off", "2026-01-01T00:00:00Z", {"source": "test"})
    db.append_samples("run-off", [{"i": i} for i in range(10)])

    rows0 = [s for b in db.iter_run_samples("run-off", offset=0) for s in b]
    assert [r["i"] for r in rows0] == list(range(10))

    rows1 = [s for b in db.iter_run_samples("run-off", offset=1) for s in b]
    assert [r["i"] for r in rows1] == list(range(1, 10))

    rows5 = [s for b in db.iter_run_samples("run-off", batch_size=3, offset=5) for s in b]
    assert [r["i"] for r in rows5] == [5, 6, 7, 8, 9]

    rows_past = [s for b in db.iter_run_samples("run-off", offset=20) for s in b]
    assert rows_past == []


def test_iter_run_samples_skips_corrupt_rows_and_continues(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-corrupt", "2026-01-01T00:00:00Z", {"source": "test"})
    db.append_samples("run-corrupt", [{"i": 1}, {"i": 2}])
    with db._cursor() as cur:
        cur.execute(
            "INSERT INTO samples_v2 (run_id, top_peaks) VALUES (?, ?)",
            ("run-corrupt", "{bad"),
        )
    db.append_samples("run-corrupt", [{"i": 3}])

    rows = [
        sample for batch in db.iter_run_samples("run-corrupt", batch_size=2) for sample in batch
    ]
    assert len(rows) == 4
    assert rows[0].get("i") == 1
    assert rows[1].get("i") == 2
    assert rows[2].get("top_peaks") == []
    assert rows[3].get("i") == 3


def test_v2_row_to_dict_non_list_peak_column_warns_and_uses_empty(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-peak-warn", "2026-01-01T00:00:00Z", {"source": "test"})

    with db._cursor() as cur:
        cur.execute(
            "INSERT INTO samples_v2 (run_id, top_peaks) VALUES (?, ?)",
            ("run-peak-warn", '{"unexpected": "dict"}'),
        )

    import logging

    with caplog.at_level(logging.WARNING, logger="vibesensor.history_db"):
        rows = db.get_run_samples("run-peak-warn")

    assert len(rows) == 1
    assert rows[0]["top_peaks"] == []
    assert "top_peaks" in caplog.text
