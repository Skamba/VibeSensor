from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import pytest

from vibesensor.history_db import HistoryDB


def test_append_samples_in_chunks(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-1", "2026-01-01T00:00:00Z", {"source": "test"})
    calls: list[int] = []
    original_cursor = db._cursor

    @contextmanager
    def _wrapped_cursor():
        with original_cursor() as cur:

            class _CursorProxy:
                def __init__(self, base_cursor):
                    self._base_cursor = base_cursor

                def __getattr__(self, name: str):
                    return getattr(self._base_cursor, name)

                def executemany(self, sql: str, seq_of_parameters):
                    rows = list(seq_of_parameters)
                    calls.append(len(rows))
                    return self._base_cursor.executemany(sql, rows)

            yield _CursorProxy(cur)

    db._cursor = _wrapped_cursor  # type: ignore[method-assign]
    samples = [{"i": i, "x": 0.1} for i in range(700)]
    db.append_samples("run-1", samples)
    assert sum(calls) == 700
    assert max(calls) <= 256
    assert len(calls) >= 3


def test_history_db_thread_safe_appends(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-2", "2026-01-01T00:00:00Z", {"source": "test"})

    def _append(start: int) -> None:
        batch = [{"i": start + i} for i in range(50)]
        db.append_samples("run-2", batch)

    with ThreadPoolExecutor(max_workers=4) as pool:
        for offset in range(0, 400, 50):
            pool.submit(_append, offset)

    assert len(db.get_run_samples("run-2")) == 400


def test_schema_version_mismatch_fails_fast(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO schema_meta (key, value) VALUES ('version', '0')")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="Unsupported history DB schema version"):
        HistoryDB(db_path)


def test_iter_run_samples_batches(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-3", "2026-01-01T00:00:00Z", {"source": "test"})
    db.append_samples("run-3", [{"i": i} for i in range(11)])
    batches = list(db.iter_run_samples("run-3", batch_size=4))
    assert [len(batch) for batch in batches] == [4, 4, 3]


def test_read_transaction_blocks_concurrent_delete_during_iteration(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-tx", "2026-01-01T00:00:00Z", {"source": "test"})
    db.append_samples("run-tx", [{"i": i} for i in range(10)])
    seen: list[int] = []
    with ThreadPoolExecutor(max_workers=1) as pool:
        with db.read_transaction():
            delete_future = pool.submit(db.delete_run, "run-tx")
            for batch in db.iter_run_samples("run-tx", batch_size=3):
                seen.extend(int(row["i"]) for row in batch)
            assert not delete_future.done()
        assert delete_future.result(timeout=2.0) is True
    assert seen == list(range(10))


def test_list_runs_uses_incremental_sample_count(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-4", "2026-01-01T00:00:00Z", {"source": "test"})
    db.append_samples("run-4", [{"i": 1}, {"i": 2}, {"i": 3}])
    run = db.list_runs()[0]
    assert run["sample_count"] == 3


def test_recover_stale_recording_runs_marks_error(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-5", "2026-01-01T00:00:00Z", {"source": "test"})
    recovered = db.recover_stale_recording_runs()
    assert recovered == 1
    run = db.get_run("run-5")
    assert run is not None
    assert run["status"] == "error"


def test_create_run_recovers_previous_recording(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-old", "2026-01-01T00:00:00Z", {"source": "test"})
    db.create_run("run-new", "2026-01-01T00:01:00Z", {"source": "test"})
    old_run = db.get_run("run-old")
    new_run = db.get_run("run-new")
    assert old_run is not None and old_run["status"] == "error"
    assert new_run is not None and new_run["status"] == "recording"


def test_future_schema_version_raises(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO schema_meta (key, value) VALUES ('version', '99')")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="Unsupported history DB schema version"):
        HistoryDB(db_path)


def test_delete_run_cascades_samples(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-del", "2026-01-01T00:00:00Z", {"source": "test"})
    db.append_samples("run-del", [{"i": i} for i in range(5)])
    assert len(db.get_run_samples("run-del")) == 5

    db.delete_run("run-del")

    # Verify samples are gone at the SQL level (CASCADE)
    with db._cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM samples_v2 WHERE run_id = ?", ("run-del",))
        assert cur.fetchone()[0] == 0


def test_run_status_transitions(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")

    # recording → analyzing → complete
    db.create_run("run-st", "2026-01-01T00:00:00Z", {"source": "test"})
    assert db.get_run_status("run-st") == "recording"

    db.finalize_run("run-st", "2026-01-01T00:10:00Z")
    assert db.get_run_status("run-st") == "analyzing"

    db.store_analysis("run-st", {"score": 42})
    assert db.get_run_status("run-st") == "complete"

    # analyzing → error via store_analysis_error
    db.create_run("run-err", "2026-01-01T00:00:00Z", {"source": "test"})
    db.finalize_run("run-err", "2026-01-01T00:10:00Z")
    db.store_analysis_error("run-err", "something went wrong")
    assert db.get_run_status("run-err") == "error"


def test_update_run_metadata_overwrites_stored_metadata(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-meta", "2026-01-01T00:00:00Z", {"tire_width_mm": 245.0})
    assert db.update_run_metadata("run-meta", {"tire_width_mm": 285.0}) is True
    run = db.get_run("run-meta")
    assert run is not None
    assert run["metadata"]["tire_width_mm"] == 285.0


def test_append_empty_samples_is_noop(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-empty", "2026-01-01T00:00:00Z", {"source": "test"})
    db.append_samples("run-empty", [{"i": 1}])
    db.append_samples("run-empty", [])
    run = db.list_runs()[0]
    assert run["sample_count"] == 1


def test_client_names_crud(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")

    # Initially empty
    assert db.list_client_names() == {}

    # Insert
    db.upsert_client_name("client-1", "Alice")
    db.upsert_client_name("client-2", "Bob")
    names = db.list_client_names()
    assert names == {"client-1": "Alice", "client-2": "Bob"}

    # Update existing
    db.upsert_client_name("client-1", "Alice Updated")
    assert db.list_client_names()["client-1"] == "Alice Updated"

    # Delete
    assert db.delete_client_name("client-2") is True
    assert db.delete_client_name("client-2") is False
    assert "client-2" not in db.list_client_names()


def test_settings_kv_roundtrip(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")

    # Missing key returns None
    assert db.get_setting("missing") is None

    # String
    db.set_setting("name", "VibeSensor")
    assert db.get_setting("name") == "VibeSensor"

    # Integer
    db.set_setting("count", 42)
    assert db.get_setting("count") == 42

    # Float
    db.set_setting("ratio", 3.14)
    assert db.get_setting("ratio") == 3.14

    # Boolean
    db.set_setting("enabled", True)
    assert db.get_setting("enabled") is True

    # None
    db.set_setting("empty", None)
    assert db.get_setting("empty") is None

    # Dict
    db.set_setting("nested", {"a": [1, 2, 3]})
    assert db.get_setting("nested") == {"a": [1, 2, 3]}

    # Overwrite existing key
    db.set_setting("name", "Updated")
    assert db.get_setting("name") == "Updated"


def test_read_only_operations_do_not_commit(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-ro", "2026-01-01T00:00:00Z", {"source": "test"})
    db.append_samples("run-ro", [{"i": 1}, {"i": 2}])
    db.set_setting("mode", {"enabled": True})
    db.upsert_client_name("client-1", "Alice")

    class _ConnProxy:
        def __init__(self, conn):
            self._conn = conn
            self.commit_calls = 0

        def __getattr__(self, name: str):
            return getattr(self._conn, name)

        def commit(self):
            self.commit_calls += 1
            return self._conn.commit()

    proxy = _ConnProxy(db._conn)
    db._conn = proxy  # type: ignore[assignment]

    _ = db.get_run("run-ro")
    _ = db.list_runs()
    _ = list(db.iter_run_samples("run-ro", batch_size=1))
    _ = db.get_run_metadata("run-ro")
    _ = db.get_run_analysis("run-ro")
    _ = db.get_run_status("run-ro")
    _ = db.get_active_run_id()
    _ = db.get_setting("mode")
    _ = db.list_client_names()

    assert proxy.commit_calls == 0

    db.set_setting("mode", {"enabled": False})
    assert proxy.commit_calls == 1


def test_create_run_sanitizes_non_finite_metadata(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-nan", "2026-01-01T00:00:00Z", {"tire_circumference_m": float("nan")})
    run = db.get_run("run-nan")
    assert run is not None
    assert run["metadata"]["tire_circumference_m"] is None


def test_iter_run_samples_skips_corrupt_rows_and_continues(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-corrupt", "2026-01-01T00:00:00Z", {"source": "test"})
    db.append_samples("run-corrupt", [{"i": 1}, {"i": 2}])
    # Inject a row with corrupt JSON in a peak column; the row is still
    # returned (typed columns are fine) but with empty peak lists.
    with db._cursor() as cur:
        cur.execute(
            "INSERT INTO samples_v2 (run_id, top_peaks) VALUES (?, ?)",
            ("run-corrupt", "{bad"),
        )
    db.append_samples("run-corrupt", [{"i": 3}])

    rows = [
        sample for batch in db.iter_run_samples("run-corrupt", batch_size=2) for sample in batch
    ]
    # The corrupt row has no 'i' key but is still returned (with empty peaks)
    assert len(rows) == 4
    assert rows[0].get("i") == 1
    assert rows[1].get("i") == 2
    assert rows[2].get("top_peaks") == []  # corrupt JSON → empty list
    assert rows[3].get("i") == 3


# -- Structured storage (v5) tests -------------------------------------------


def _sensor_frame_dict(i: int, *, run_id: str = "run-v2") -> dict:
    """Build a realistic SensorFrame-shaped dict for testing."""
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
    """SensorFrame-shaped samples round-trip through structured storage."""
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
    """Dict keys not in SensorFrame are preserved via extra_json column."""
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
    """NaN and Inf float values are stored as NULL (sanitized)."""
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-nan", "2026-01-01T00:00:00Z", {"source": "test"})
    sample = {"speed_kmh": float("nan"), "accel_x_g": float("inf"), "t_s": 1.0}
    db.append_samples("run-nan", [sample])

    rows = db.get_run_samples("run-nan")
    assert len(rows) == 1
    assert "speed_kmh" not in rows[0]  # NaN → NULL → omitted
    assert "accel_x_g" not in rows[0]  # Inf → NULL → omitted
    assert rows[0]["t_s"] == 1.0


def test_v2_no_json_blobs_in_storage(tmp_path: Path) -> None:
    """Verify that the samples_v2 table does not use a sample_json column."""
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


def test_v4_to_v5_migration(tmp_path: Path) -> None:
    """Opening a v4 database auto-migrates to v5 with legacy data readable."""
    db_path = tmp_path / "history.db"

    # Create a v4 database manually
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
    # Insert legacy run with JSON-blob samples
    conn.execute(
        "INSERT INTO runs (run_id, status, start_time_utc, metadata_json,"
        " created_at, sample_count) "
        "VALUES (?, 'complete', '2026-01-01T00:00:00Z', '{}', "
        "'2026-01-01T00:00:00Z', 3)",
        ("legacy-run",),
    )
    for i in range(3):
        conn.execute(
            "INSERT INTO samples (run_id, sample_json) VALUES (?, ?)",
            ("legacy-run", json.dumps({"i": i, "speed_kmh": 60.0 + i})),
        )
    conn.commit()
    conn.close()

    # Open with HistoryDB — should migrate v4 → v5
    db = HistoryDB(db_path)

    # Legacy samples are still readable
    rows = db.get_run_samples("legacy-run")
    assert len(rows) == 3
    assert [row["i"] for row in rows] == [0, 1, 2]
    assert [row["speed_kmh"] for row in rows] == [60.0, 61.0, 62.0]

    # New samples go to structured table
    db.create_run("new-run", "2026-01-02T00:00:00Z", {"source": "test"})
    db.append_samples("new-run", [_sensor_frame_dict(0, run_id="new-run")])
    new_rows = db.get_run_samples("new-run")
    assert len(new_rows) == 1
    assert new_rows[0]["speed_kmh"] == 60.0

    # Schema version is now 5
    with db._cursor(commit=False) as cur:
        cur.execute("SELECT value FROM schema_meta WHERE key = 'version'")
        assert cur.fetchone()[0] == "5"

    db.close()


def test_v2_sensor_frame_objects(tmp_path: Path) -> None:
    """SensorFrame objects (not just dicts) can be stored and retrieved."""
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
    """Deleting a run cascades to samples_v2 rows."""
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-del2", "2026-01-01T00:00:00Z", {"source": "test"})
    db.append_samples("run-del2", [_sensor_frame_dict(i, run_id="run-del2") for i in range(3)])

    assert len(db.get_run_samples("run-del2")) == 3
    db.delete_run("run-del2")

    with db._cursor(commit=False) as cur:
        cur.execute("SELECT COUNT(*) FROM samples_v2 WHERE run_id = ?", ("run-del2",))
        assert cur.fetchone()[0] == 0


def test_v2_record_then_export_roundtrip(tmp_path: Path) -> None:
    """Full record → finalize → analyze → read cycle with structured storage."""
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-full", "2026-01-01T00:00:00Z", {"source": "roundtrip"})

    # Simulate recording
    for batch_start in range(0, 20, 5):
        batch = [
            _sensor_frame_dict(i, run_id="run-full")
            for i in range(batch_start, batch_start + 5)
        ]
        db.append_samples("run-full", batch)

    db.finalize_run("run-full", "2026-01-01T00:00:20Z")
    assert db.get_run_status("run-full") == "analyzing"

    db.store_analysis("run-full", {"score": 42})
    assert db.get_run_status("run-full") == "complete"

    # Read back all samples
    all_samples = db.get_run_samples("run-full")
    assert len(all_samples) == 20

    # Iterate in batches
    batched = list(db.iter_run_samples("run-full", batch_size=7))
    flat = [s for b in batched for s in b]
    assert len(flat) == 20
    assert [s["t_s"] for s in flat] == [float(i) for i in range(20)]

    # Run metadata
    run = db.get_run("run-full")
    assert run is not None
    assert run["sample_count"] == 20
    assert run["status"] == "complete"
    analysis = db.get_run_analysis("run-full")
    assert analysis is not None
    assert analysis["score"] == 42


def test_v2_iter_with_offset(tmp_path: Path) -> None:
    """Offset-based iteration works with structured samples."""
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-off", "2026-01-01T00:00:00Z", {"source": "test"})
    db.append_samples("run-off", [{"i": i} for i in range(10)])

    # offset=0 → all rows
    rows0 = [s for b in db.iter_run_samples("run-off", offset=0) for s in b]
    assert [r["i"] for r in rows0] == list(range(10))

    # offset=1 → skip first row
    rows1 = [s for b in db.iter_run_samples("run-off", offset=1) for s in b]
    assert [r["i"] for r in rows1] == list(range(1, 10))

    # offset=5 with batch_size=3
    rows5 = [
        s
        for b in db.iter_run_samples("run-off", batch_size=3, offset=5)
        for s in b
    ]
    assert [r["i"] for r in rows5] == [5, 6, 7, 8, 9]

    # offset >= total → empty
    rows_past = [
        s for b in db.iter_run_samples("run-off", offset=20) for s in b
    ]
    assert rows_past == []
