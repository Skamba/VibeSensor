from __future__ import annotations

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
        cur.execute("SELECT COUNT(*) FROM samples WHERE run_id = ?", ("run-del",))
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
