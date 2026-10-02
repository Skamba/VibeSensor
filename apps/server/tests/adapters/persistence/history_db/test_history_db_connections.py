"""HistoryDB connection-mode, transaction-cleanup, and thread-concurrency coverage."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread

import pytest
from test_support.history_db_lifecycle import make_run_metadata as _metadata
from test_support.history_db_sql import fetch_all, fetch_one

from vibesensor.adapters.persistence.history_db._history_db import HistoryDB
from vibesensor.recording.sensor_frame_mapping import sensor_frame_from_mapping


class _AbortTxn(BaseException):
    pass


def test_history_db_read_connection_is_query_only(db: HistoryDB) -> None:
    assert db._read_conn is not None
    row = fetch_one(db, "PRAGMA query_only")
    assert row is not None
    assert int(row[0]) == 1


def test_history_db_read_errors_clear_read_transaction(db: HistoryDB) -> None:
    assert db._read_conn is not None
    with pytest.raises(sqlite3.OperationalError):
        fetch_all(db, "SELECT * FROM missing_table")
    assert not db._read_conn.in_transaction


def test_history_db_read_base_exception_clears_read_transaction(db: HistoryDB) -> None:
    db.create_run("run-read-abort", "2026-01-01T00:00:00Z", _metadata("run-read-abort"))
    assert db._read_conn is not None
    with pytest.raises(_AbortTxn):
        rows = fetch_all(db, "SELECT * FROM runs WHERE run_id = ?", ("run-read-abort",))
        assert rows
        raise _AbortTxn
    assert not db._read_conn.in_transaction
    assert [run.run_id for run in db.list_runs()] == ["run-read-abort"]


@pytest.mark.parametrize("immediate", [False, True])
def test_history_db_write_base_exception_rolls_back(db: HistoryDB, immediate: bool) -> None:
    db.create_run("run-write", "2026-01-01T00:00:00Z", _metadata("run-write"))
    with pytest.raises(_AbortTxn), db._write(immediate=immediate) as cur:
        cur.execute("UPDATE runs SET sample_count = 7 WHERE run_id = ?", ("run-write",))
        raise _AbortTxn
    assert db._conn is not None
    assert not db._conn.in_transaction
    run = db.get_run("run-write")
    assert run is not None
    assert run.sample_count == 0


def test_history_db_allows_reads_during_write_transaction(db: HistoryDB) -> None:
    db.create_run("run-read", "2026-01-01T00:00:00Z", _metadata("run-read"))
    read_finished = Event()
    errors: list[BaseException] = []

    def _reader() -> None:
        try:
            assert [run.run_id for run in db.list_runs()] == ["run-read"]
        except BaseException as exc:  # pragma: no cover - re-raised in test thread
            errors.append(exc)
        finally:
            read_finished.set()

    with db._write(immediate=True) as cur:
        cur.execute(
            "UPDATE runs SET error_message = ? WHERE run_id = ?",
            ("pending", "run-read"),
        )
        thread = Thread(target=_reader)
        thread.start()
        assert read_finished.wait(2.0), "reader blocked behind the open write transaction"
        thread.join(timeout=1.0)

    if errors:
        raise errors[0]


def test_concurrent_writer_and_reader_threads_converge(db: HistoryDB) -> None:
    run_id = "run-concurrent"
    db.create_run(run_id, "2026-01-01T00:00:00Z", _metadata(run_id))

    def _append(offset: int) -> int:
        frames = [sensor_frame_from_mapping({"i": offset + i}) for i in range(20)]
        return db.append_samples(run_id, frames)

    def _read(_: int) -> int:
        return len(db.list_runs())

    with ThreadPoolExecutor(max_workers=6) as pool:
        appended = list(pool.map(_append, range(0, 200, 20)))
        reads = list(pool.map(_read, range(10)))

    assert sum(appended) == 200
    assert reads == [1] * 10
    samples = [frame for batch in db.iter_run_samples(run_id) for frame in batch]
    assert len(samples) == 200
    run = db.get_run(run_id)
    assert run is not None
    assert run.sample_count == 200


def test_operations_after_close_raise(db: HistoryDB) -> None:
    db.close()
    with pytest.raises(RuntimeError, match="closed"):
        db.list_runs()
    with pytest.raises(RuntimeError, match="closed"):
        db.create_run("run-closed", "2026-01-01T00:00:00Z", _metadata("run-closed"))
