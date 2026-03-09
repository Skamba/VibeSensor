from __future__ import annotations

import logging
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
    original_write_tx = db.write_transaction_cursor

    @contextmanager
    def _wrapped_write_transaction():
        with original_write_tx() as cur:

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

    db.write_transaction_cursor = _wrapped_write_transaction  # type: ignore[method-assign]
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


@pytest.mark.parametrize("bad_version", ["0", "99"], ids=["ancient", "future"])
def test_schema_version_mismatch_fails_fast(tmp_path: Path, bad_version: str) -> None:
    db_path = tmp_path / "history.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO schema_meta (key, value) VALUES ('version', ?)", (bad_version,))
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
    assert "Recovered stale recording during startup at" in str(run["error_message"])


def test_create_run_recovers_previous_recording(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-old", "2026-01-01T00:00:00Z", {"source": "test"})
    db.create_run("run-new", "2026-01-01T00:01:00Z", {"source": "test"})
    old_run = db.get_run("run-old")
    new_run = db.get_run("run-new")
    assert old_run is not None and old_run["status"] == "error"
    assert "starting run run-new" in str(old_run["error_message"])
    assert new_run is not None and new_run["status"] == "recording"


def test_delete_run_cascades_samples(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-del", "2026-01-01T00:00:00Z", {"source": "test"})
    db.append_samples("run-del", [{"i": i} for i in range(5)])
    assert len(db.get_run_samples("run-del")) == 5

    db.delete_run("run-del")

    with db._cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM samples_v2 WHERE run_id = ?", ("run-del",))
        assert cur.fetchone()[0] == 0


def test_run_status_transitions(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")

    db.create_run("run-st", "2026-01-01T00:00:00Z", {"source": "test"})
    assert db.get_run_status("run-st") == "recording"

    db.finalize_run("run-st", "2026-01-01T00:10:00Z")
    assert db.get_run_status("run-st") == "analyzing"

    db.store_analysis("run-st", {"score": 42})
    assert db.get_run_status("run-st") == "complete"

    db.create_run("run-err", "2026-01-01T00:00:00Z", {"source": "test"})
    db.finalize_run("run-err", "2026-01-01T00:10:00Z")
    db.store_analysis_error("run-err", "something went wrong")
    assert db.get_run_status("run-err") == "error"


def test_store_analysis_allows_direct_recording_to_complete(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-recording", "2026-01-01T00:00:00Z", {"source": "test"})

    stored = db.store_analysis("run-recording", {"score": 42})

    assert stored is True
    run = db.get_run("run-recording")
    assert run is not None
    assert run["status"] == "complete"
    assert run.get("analysis") == {"score": 42}


def test_append_samples_rolls_back_when_metadata_update_fails(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-rollback", "2026-01-01T00:00:00Z", {"source": "test"})
    original_write_tx = db.write_transaction_cursor

    @contextmanager
    def _wrapped_write_transaction():
        with original_write_tx() as cur:

            class _CursorProxy:
                def __init__(self, base_cursor):
                    self._base_cursor = base_cursor

                def __getattr__(self, name: str):
                    return getattr(self._base_cursor, name)

                def execute(self, sql: str, params=()):
                    if "UPDATE runs SET sample_count = sample_count + ?" in sql:
                        raise sqlite3.OperationalError("simulated sample_count failure")
                    return self._base_cursor.execute(sql, params)

            yield _CursorProxy(cur)

    db.write_transaction_cursor = _wrapped_write_transaction  # type: ignore[method-assign]

    with pytest.raises(sqlite3.OperationalError, match="simulated sample_count failure"):
        db.append_samples("run-rollback", [{"i": 1}, {"i": 2}])

    run = db.get_run("run-rollback")
    assert run is not None
    assert run["sample_count"] == 0
    assert db.get_run_samples("run-rollback") == []


def test_finalize_run_with_metadata_returns_false_when_already_analyzing(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-finalize", "2026-01-01T00:00:00Z", {"source": "test"})

    assert (
        db.finalize_run_with_metadata(
            "run-finalize",
            "2026-01-01T00:05:00Z",
            {"source": "test", "step": 1},
        )
        is True
    )
    assert (
        db.finalize_run_with_metadata(
            "run-finalize",
            "2026-01-01T00:06:00Z",
            {"source": "test", "step": 2},
        )
        is False
    )


def test_analyzing_run_health_reports_oldest_age(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-an", "2026-01-01T00:00:00Z", {"source": "test"})
    db.finalize_run("run-an", "2026-01-01T00:01:00Z")

    health = db.analyzing_run_health()

    assert health["analyzing_run_count"] == 1
    assert isinstance(health.get("analyzing_oldest_age_s"), float)


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

    assert db.list_client_names() == {}

    db.upsert_client_name("client-1", "Alice")
    db.upsert_client_name("client-2", "Bob")
    names = db.list_client_names()
    assert names == {"client-1": "Alice", "client-2": "Bob"}

    db.upsert_client_name("client-1", "Alice Updated")
    assert db.list_client_names()["client-1"] == "Alice Updated"

    assert db.delete_client_name("client-2") is True
    assert db.delete_client_name("client-2") is False
    assert "client-2" not in db.list_client_names()


def test_settings_kv_roundtrip(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")

    assert db.get_setting("missing") is None

    db.set_setting("name", "VibeSensor")
    assert db.get_setting("name") == "VibeSensor"

    db.set_setting("count", 42)
    assert db.get_setting("count") == 42

    db.set_setting("ratio", 3.14)
    assert db.get_setting("ratio") == 3.14

    db.set_setting("enabled", True)
    assert db.get_setting("enabled") is True

    db.set_setting("empty", None)
    assert db.get_setting("empty") is None

    db.set_setting("nested", {"a": [1, 2, 3]})
    assert db.get_setting("nested") == {"a": [1, 2, 3]}

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


def test_get_run_metadata_non_dict_json_returns_none_and_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-bad-meta", "2026-01-01T00:00:00Z", {"source": "test"})
    with db._cursor() as cur:
        cur.execute(
            "UPDATE runs SET metadata_json = ? WHERE run_id = ?",
            ("[1, 2, 3]", "run-bad-meta"),
        )

    with caplog.at_level(logging.WARNING, logger="vibesensor.history_db"):
        result = db.get_run_metadata("run-bad-meta")

    assert result is None
    assert "run-bad-meta" in caplog.text
    assert "metadata_json" in caplog.text


def test_close_is_idempotent(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.close()
    db.close()


def test_operations_after_close_raise(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.close()
    with pytest.raises(RuntimeError, match="closed"):
        db.create_run("run-x", "2026-01-01T00:00:00Z", {})


# ---------------------------------------------------------------------------
# Schema v5 → v6 migration
# ---------------------------------------------------------------------------

_V5_SCHEMA_SQL = """\
CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
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
CREATE TABLE samples_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    record_type TEXT, schema_version TEXT, timestamp_utc TEXT, t_s REAL,
    client_id TEXT, client_name TEXT, location TEXT, sample_rate_hz INTEGER,
    speed_kmh REAL, gps_speed_kmh REAL, speed_source TEXT,
    engine_rpm REAL, engine_rpm_source TEXT, gear REAL, final_drive_ratio REAL,
    accel_x_g REAL, accel_y_g REAL, accel_z_g REAL,
    dominant_freq_hz REAL, dominant_axis TEXT,
    vibration_strength_db REAL, strength_bucket TEXT,
    strength_peak_amp_g REAL, strength_floor_amp_g REAL,
    frames_dropped_total INTEGER DEFAULT 0, queue_overflow_drops INTEGER DEFAULT 0,
    top_peaks TEXT, top_peaks_x TEXT, top_peaks_y TEXT, top_peaks_z TEXT,
    extra_json TEXT
);
CREATE INDEX idx_samples_v2_run_id ON samples_v2(run_id);
CREATE INDEX idx_samples_v2_run_time ON samples_v2(run_id, t_s);
CREATE INDEX idx_runs_status ON runs(status);
CREATE INDEX idx_runs_created_at ON runs(created_at);
CREATE TABLE settings_kv (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE client_names (
    client_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
INSERT INTO schema_meta (key, value) VALUES ('version', '5');
"""


def _make_v5_db(db_path: Path) -> None:
    """Create a v5 schema database directly without migrating."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_V5_SCHEMA_SQL)
    conn.commit()
    conn.close()


def _index_names(db_path: Path) -> set[str]:
    """Return all index names in the database."""
    conn = sqlite3.connect(str(db_path))
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
    )
    names = {row[0] for row in cur.fetchall()}
    conn.close()
    return names


def test_schema_v5_migrates_to_v6(tmp_path: Path) -> None:
    """Opening a v5 database automatically migrates it to v6."""
    db_path = tmp_path / "v5.db"
    _make_v5_db(db_path)

    before_indexes = _index_names(db_path)
    assert "idx_samples_v2_client_time" not in before_indexes
    assert "idx_runs_status_created" not in before_indexes

    db = HistoryDB(db_path)
    db.close()

    after_indexes = _index_names(db_path)
    assert "idx_samples_v2_client_time" in after_indexes, "migration must add client_time index"
    assert "idx_runs_status_created" in after_indexes, "migration must add status_created index"

    conn = sqlite3.connect(str(db_path))
    cur = conn.execute("SELECT value FROM schema_meta WHERE key = 'version'")
    row = cur.fetchone()
    conn.close()
    assert row is not None and row[0] == "6", "version must be bumped to 6 after migration"


def test_schema_v5_migration_is_idempotent(tmp_path: Path) -> None:
    """Opening a v5 database twice does not fail (migration is idempotent)."""
    db_path = tmp_path / "v5_idempotent.db"
    _make_v5_db(db_path)

    db1 = HistoryDB(db_path)
    db1.close()

    db2 = HistoryDB(db_path)
    db2.close()

    after_indexes = _index_names(db_path)
    assert "idx_samples_v2_client_time" in after_indexes
    assert "idx_runs_status_created" in after_indexes


def test_schema_v5_migration_preserves_existing_data(tmp_path: Path) -> None:
    """Existing runs and samples in a v5 database survive the v6 migration."""
    db_path = tmp_path / "v5_data.db"
    _make_v5_db(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO runs (run_id, status, start_time_utc, metadata_json, created_at) "
        "VALUES ('run-pre', 'complete', '2026-01-01T00:00:00Z', '{}', '2026-01-01T00:00:00Z')"
    )
    conn.commit()
    conn.close()

    db = HistoryDB(db_path)
    run = db.get_run("run-pre")
    db.close()

    assert run is not None
    assert run["run_id"] == "run-pre"
    assert run["status"] == "complete"


# ---------------------------------------------------------------------------
# create_run atomicity
# ---------------------------------------------------------------------------


def test_create_run_rollsback_stale_recovery_on_insert_failure(tmp_path: Path) -> None:
    """If the INSERT in create_run fails, the preceding UPDATE must be rolled back.

    This verifies the two-statement sequence (stale-run recovery UPDATE + new-run
    INSERT) executes as a single atomic transaction, not two separate commits.
    """
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-stale", "2026-01-01T00:00:00Z", {"source": "test"})

    original_write_tx = db.write_transaction_cursor

    @contextmanager
    def _wrapped_write_transaction():
        with original_write_tx() as cur:

            class _FailOnInsert:
                def __init__(self, base_cursor):
                    self._base = base_cursor

                def __getattr__(self, name: str):
                    return getattr(self._base, name)

                def execute(self, sql: str, params=()):
                    if "INSERT INTO runs" in sql:
                        raise sqlite3.IntegrityError("simulated INSERT failure")
                    return self._base.execute(sql, params)

            yield _FailOnInsert(cur)

    db.write_transaction_cursor = _wrapped_write_transaction  # type: ignore[method-assign]

    with pytest.raises(sqlite3.IntegrityError, match="simulated INSERT failure"):
        db.create_run("run-new", "2026-01-01T00:01:00Z", {"source": "test"})

    stale = db.get_run("run-stale")
    assert stale is not None, "stale run must still exist after failed create_run"
    assert stale["status"] == "recording", (
        "UPDATE (stale-run recovery) must be rolled back when INSERT fails"
    )
