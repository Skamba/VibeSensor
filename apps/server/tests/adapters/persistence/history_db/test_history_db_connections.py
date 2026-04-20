"""HistoryDB connection-mode and transaction-cleanup regression coverage."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from threading import Event, Thread

import pytest
from test_support.history_db_async import fetch_all, fetch_one

from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
from vibesensor.shared.async_bridge import run_coro_blocking
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.types.run_schema import RunMetadata


class _AbortTxn(BaseException):
    pass


def _metadata(run_id: str) -> RunMetadata:
    return run_metadata_from_mapping(
        {
            "run_id": run_id,
            "start_time_utc": "2026-01-01T00:00:00Z",
            "sensor_model": "ADXL345",
            "raw_sample_rate_hz": 800,
            "sample_rate_hz": 800,
            "feature_interval_s": 1.0,
            "source": "test",
        }
    )


def test_history_db_read_connection_is_query_only(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    try:
        assert db.lifecycle._read_conn is not None
        row = fetch_one(db.lifecycle, "PRAGMA query_only")
        assert row is not None
        assert int(row[0]) == 1
    finally:
        db.lifecycle.close()


def test_history_db_read_errors_clear_read_transaction(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    try:
        assert db.lifecycle._read_conn is not None
        with pytest.raises(sqlite3.OperationalError):
            fetch_all(db.lifecycle, "SELECT * FROM missing_table")
        assert not db.lifecycle._read_conn.in_transaction
    finally:
        db.lifecycle.close()


def test_history_db_read_base_exception_clears_read_transaction(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    try:
        db.run_repository.create_run(
            "run-read-abort", "2026-01-01T00:00:00Z", _metadata("run-read-abort")
        )
        assert db.lifecycle._read_conn is not None
        with pytest.raises(_AbortTxn):
            rows = fetch_all(
                db.lifecycle,
                "SELECT * FROM runs WHERE run_id = ?",
                ("run-read-abort",),
            )
            assert rows
            raise _AbortTxn
        assert not db.lifecycle._read_conn.in_transaction
        assert [run.run_id for run in db.run_repository.list_runs()] == ["run-read-abort"]
    finally:
        db.lifecycle.close()


def test_history_db_write_cursor_base_exception_rolls_back(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    try:
        db.run_repository.create_run(
            "run-write-cursor", "2026-01-01T00:00:00Z", _metadata("run-write-cursor")
        )
        with pytest.raises(_AbortTxn):

            async def _run() -> None:
                async with db.lifecycle._cursor_async() as cur:
                    await cur.execute(
                        "UPDATE runs SET sample_count = 7 WHERE run_id = ?",
                        ("run-write-cursor",),
                    )
                    raise _AbortTxn

            run_coro_blocking(_run())
        assert not db.lifecycle._conn.in_transaction
        run = db.run_repository.get_run("run-write-cursor")
        assert run is not None
        assert run.sample_count == 0
    finally:
        db.lifecycle.close()


def test_history_db_write_transaction_base_exception_rolls_back(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    try:
        db.run_repository.create_run(
            "run-write-tx", "2026-01-01T00:00:00Z", _metadata("run-write-tx")
        )
        with pytest.raises(_AbortTxn):

            async def _run() -> None:
                async with db.lifecycle.write_transaction_cursor_async() as cur:
                    await cur.execute(
                        "UPDATE runs SET sample_count = 9 WHERE run_id = ?",
                        ("run-write-tx",),
                    )
                    raise _AbortTxn

            run_coro_blocking(_run())
        assert not db.lifecycle._conn.in_transaction
        run = db.run_repository.get_run("run-write-tx")
        assert run is not None
        assert run.sample_count == 0
    finally:
        db.lifecycle.close()


def test_history_db_allows_reads_during_write_transaction(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run("run-read", "2026-01-01T00:00:00Z", _metadata("run-read"))
    read_started = Event()
    read_finished = Event()
    errors: list[BaseException] = []

    def _reader() -> None:
        read_started.set()
        try:
            runs = db.run_repository.list_runs()
            assert [run.run_id for run in runs] == ["run-read"]
        except BaseException as exc:  # pragma: no cover - re-raised in test thread
            errors.append(exc)
        finally:
            read_finished.set()

    async def _run_transaction() -> None:
        async with db.lifecycle.write_transaction_cursor_async() as cur:
            await cur.execute(
                "UPDATE runs SET error_message = ? WHERE run_id = ?",
                ("pending", "run-read"),
            )
            thread = Thread(target=_reader)
            thread.start()
            try:
                assert await asyncio.to_thread(read_started.wait, 1.0)
                assert await asyncio.to_thread(read_finished.wait, 1.0)
            finally:
                thread.join(timeout=1.0)

    run_coro_blocking(_run_transaction())

    db.lifecycle.close()
    if errors:
        raise errors[0]
