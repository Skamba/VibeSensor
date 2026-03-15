from __future__ import annotations

import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import pytest

from vibesensor.adapters.persistence.history_db import HistoryDB


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


def test_schema_version_ancient_no_migration_fails_fast(tmp_path: Path) -> None:
    """A DB with a very old version that has no migration path should raise."""
    db_path = tmp_path / "history.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="incompatible"):
        HistoryDB(db_path)


def test_schema_version_future_fails_fast(tmp_path: Path) -> None:
    """A DB with a newer version than supported should raise (no downgrade)."""
    db_path = tmp_path / "history.db"
    # Create a valid current-version DB first so the physical schema is correct
    db = HistoryDB(db_path)
    db.close()
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA user_version = 99")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="Cannot downgrade"):
        HistoryDB(db_path)


def test_iter_run_samples_batches(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-3", "2026-01-01T00:00:00Z", {"source": "test"})
    db.append_samples("run-3", [{"i": i} for i in range(11)])
    batches = list(db.iter_run_samples("run-3", batch_size=4))
    assert [len(batch) for batch in batches] == [4, 4, 3]


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


def test_create_run_persists_case_id(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")

    db.create_run(
        "run-case-create",
        "2026-01-01T00:00:00Z",
        {"source": "test"},
        case_id="case-123",
    )

    run = db.get_run("run-case-create")
    assert run is not None
    assert run["case_id"] == "case-123"


def test_create_run_logs_stale_recovery(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-old", "2026-01-01T00:00:00Z", {"source": "test"})
    with caplog.at_level(logging.WARNING, logger="vibesensor.adapters.persistence.history_db._run_writes"):
        db.create_run("run-new", "2026-01-01T00:01:00Z", {"source": "test"})
    assert any("stale recording" in r.message.lower() for r in caplog.records)


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
    assert db.get_run("run-st")["status"] == "recording"

    db.finalize_run("run-st", "2026-01-01T00:10:00Z")
    assert db.get_run("run-st")["status"] == "analyzing"

    db.store_analysis("run-st", {"score": 42})
    assert db.get_run("run-st")["status"] == "complete"

    db.create_run("run-err", "2026-01-01T00:00:00Z", {"source": "test"})
    db.finalize_run("run-err", "2026-01-01T00:10:00Z")
    db.store_analysis_error("run-err", "something went wrong")
    assert db.get_run("run-err")["status"] == "error"


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


def test_finalize_run_returns_false_when_already_analyzing(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-finalize", "2026-01-01T00:00:00Z", {"source": "test"})

    assert (
        db.finalize_run(
            "run-finalize",
            "2026-01-01T00:05:00Z",
            metadata={"source": "test", "step": 1},
        )
        is True
    )
    assert (
        db.finalize_run(
            "run-finalize",
            "2026-01-01T00:06:00Z",
            metadata={"source": "test", "step": 2},
        )
        is False
    )


def test_finalize_run_persists_case_id(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-case-finalize", "2026-01-01T00:00:00Z", {"source": "test"})

    assert (
        db.finalize_run(
            "run-case-finalize",
            "2026-01-01T00:05:00Z",
            metadata={"source": "test", "step": 1},
            case_id="case-456",
        )
        is True
    )

    run = db.get_run("run-case-finalize")
    assert run is not None
    assert run["status"] == "analyzing"
    assert run["metadata"]["step"] == 1
    assert run["case_id"] == "case-456"


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


def test_read_only_operations_do_not_commit(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-ro", "2026-01-01T00:00:00Z", {"source": "test"})
    db.append_samples("run-ro", [{"i": 1}, {"i": 2}])
    db.set_settings_snapshot({"enabled": True})
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
    _ = db.get_run("run-ro").get("analysis")
    _ = db.get_run("run-ro")["status"]
    _ = db.get_active_run_id()
    _ = db.get_settings_snapshot()
    _ = db.list_client_names()

    assert proxy.commit_calls == 0

    db.set_settings_snapshot({"enabled": False})
    assert proxy.commit_calls == 1


def test_get_run_metadata_non_dict_json_returns_none_and_warns(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-bad-meta", "2026-01-01T00:00:00Z", {"source": "test"})
    with db._cursor() as cur:
        cur.execute(
            "UPDATE runs SET metadata_json = ? WHERE run_id = ?",
            ("[1, 2, 3]", "run-bad-meta"),
        )

    with caplog.at_level(logging.WARNING, logger="vibesensor.adapters.persistence.history_db"):
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
