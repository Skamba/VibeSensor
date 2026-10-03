"""RunPersistenceWriter: retry, cooldown and drop accounting over a real HistoryDB."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from threading import RLock

import pytest
from test_support.history_db_lifecycle import make_run_metadata, run_samples
from test_support.obd_runtime import FakeClock

from vibesensor.history.history_db import HistoryDB
from vibesensor.recording.persistence_writer import (
    _MAX_APPEND_RETRIES,
    _MAX_HISTORY_CREATE_RETRIES,
    _RETRY_COOLDOWN_BASE_S,
    RunPersistenceWriter,
)
from vibesensor.recording.sensor_frame import SensorFrame
from vibesensor.recording.sensor_frame_mapping import sensor_frame_from_mapping

_START = "2026-01-01T00:00:00Z"


class _FlakyHistoryDB(HistoryDB):
    """Real HistoryDB whose create/append fail a configurable number of times."""

    def __init__(self, path: Path, *, create_failures: int = 0, append_failures: int = 0):
        super().__init__(path)
        self.create_failures = create_failures
        self.append_failures = append_failures

    def create_run(self, run_id, start_time_utc, metadata) -> None:
        if self.create_failures > 0:
            self.create_failures -= 1
            raise sqlite3.OperationalError("db locked")
        super().create_run(run_id, start_time_utc, metadata)

    def append_samples(self, run_id: str, samples: list[SensorFrame]) -> int:
        if self.append_failures > 0:
            self.append_failures -= 1
            raise sqlite3.OperationalError("disk full")
        return super().append_samples(run_id, samples)


def _rows(count: int) -> list[SensorFrame]:
    return [sensor_frame_from_mapping({"t_s": float(i)}) for i in range(count)]


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(now=100.0)


@pytest.fixture
def make_writer(tmp_path: Path, clock: FakeClock):
    dbs: list[HistoryDB] = []

    def _factory(**failures: int) -> tuple[RunPersistenceWriter, HistoryDB]:
        db = _FlakyHistoryDB(tmp_path / f"history-{len(dbs)}.db", **failures)
        dbs.append(db)
        writer = RunPersistenceWriter(
            lock=RLock(),
            history_db=db,
            persist_history_db_enabled=True,
            run_id_matches=lambda run_id: run_id in {"run-1", "run-2"},
            metadata_builder=lambda run_id, _start: make_run_metadata(run_id),
            monotonic=clock,
            sleep=lambda _s: None,
            logger_provider=lambda: logging.getLogger(__name__),
        )
        return writer, db

    yield _factory
    for db in dbs:
        db.close()


def test_successful_appends_persist_rows_and_count_no_drops(make_writer) -> None:
    writer, db = make_writer()

    result = writer.append_rows(run_id="run-1", start_time_utc=_START, rows=_rows(2))

    assert result.rows_written == 2
    assert len(run_samples(db, "run-1")) == 2
    snapshot = writer.status_snapshot()
    assert (snapshot.written_sample_count, snapshot.dropped_sample_count) == (2, 0)
    assert snapshot.write_error is None


def test_transient_append_failure_is_retried(make_writer) -> None:
    writer, db = make_writer(append_failures=_MAX_APPEND_RETRIES - 1)

    result = writer.append_rows(run_id="run-1", start_time_utc=_START, rows=_rows(2))

    assert result.rows_written == 2
    assert len(run_samples(db, "run-1")) == 2
    assert writer.status_snapshot().dropped_sample_count == 0


def test_exhausted_append_retries_drop_rows_and_drops_accumulate_until_reset(
    make_writer,
) -> None:
    writer, db = make_writer(append_failures=10 * _MAX_APPEND_RETRIES)

    for _ in range(3):
        result = writer.append_rows(run_id="run-1", start_time_utc=_START, rows=_rows(2))
        assert result.rows_written == 0

    snapshot = writer.status_snapshot()
    assert snapshot.dropped_sample_count == 6
    assert "append_samples failed" in str(snapshot.write_error)
    assert run_samples(db, "run-1") == []

    writer.reset()
    assert writer.status_snapshot().dropped_sample_count == 0


def test_exhausted_create_retries_drop_rows_until_the_cooldown_expires(
    make_writer,
    clock: FakeClock,
) -> None:
    writer, db = make_writer(create_failures=_MAX_HISTORY_CREATE_RETRIES)

    # Within the retry budget every append retries create_run immediately.
    for _ in range(_MAX_HISTORY_CREATE_RETRIES):
        writer.append_rows(run_id="run-1", start_time_utc=_START, rows=_rows(1))
    assert db.get_run("run-1") is None
    assert writer.status_snapshot().dropped_sample_count == _MAX_HISTORY_CREATE_RETRIES

    # Budget exhausted: no retry before the cooldown, rows are dropped.
    clock.advance(_RETRY_COOLDOWN_BASE_S - 0.1)
    assert (
        writer.append_rows(run_id="run-1", start_time_utc=_START, rows=_rows(3)).rows_written == 0
    )
    assert writer.status_snapshot().dropped_sample_count == _MAX_HISTORY_CREATE_RETRIES + 3
    assert "create_run failed" in str(writer.status_snapshot().write_error)

    # After the cooldown the run is created and writes resume.
    clock.advance(0.2)
    result = writer.append_rows(run_id="run-1", start_time_utc=_START, rows=_rows(2))
    assert result.rows_written == 2
    assert db.get_run("run-1") is not None
    assert writer.status_snapshot().write_error is None


def test_reset_restarts_the_create_retry_budget_for_a_new_run(make_writer) -> None:
    writer, db = make_writer(create_failures=_MAX_HISTORY_CREATE_RETRIES)
    for _ in range(_MAX_HISTORY_CREATE_RETRIES):
        writer.append_rows(run_id="run-1", start_time_utc=_START, rows=_rows(1))

    writer.reset()
    result = writer.append_rows(run_id="run-2", start_time_utc=_START, rows=_rows(1))

    assert result.rows_written == 1
    assert db.get_run("run-2") is not None
