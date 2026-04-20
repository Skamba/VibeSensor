"""Lifecycle, pruning, corruption, and metadata CRUD coverage for HistoryDB."""

from __future__ import annotations

import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_support.history_db_async import execute_statements as _execute_statements
from test_support.history_db_async import fetch_one as _fetch_one
from test_support.history_db_lifecycle import (
    build_history_db,
    create_analyzing_run,
    create_completed_run,
    create_error_run,
    create_recording_run,
)
from test_support.history_db_lifecycle import (
    make_analysis_summary as _analysis,
)
from test_support.history_db_lifecycle import (
    make_run_metadata as _metadata,
)
from test_support.history_db_lifecycle import (
    make_settings_snapshot as _settings_snapshot,
)
from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.adapters.persistence.history_db import (
    SQLiteHistoryEngine,
    create_history_persistence_adapters,
)
from vibesensor.shared.boundaries.sensor_frames import sensor_frame_from_mapping


def test_append_samples_in_chunks(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    create_recording_run(db, "run-1")
    calls: list[int] = []
    original_write_tx = db.run_repository._write_transaction_cursor_provider

    @asynccontextmanager
    async def _wrapped_write_transaction():
        async with original_write_tx() as cur:

            class _CursorProxy:
                def __init__(self, base_cursor):
                    self._base_cursor = base_cursor

                def __getattr__(self, name: str):
                    return getattr(self._base_cursor, name)

                async def executemany(self, sql: str, seq_of_parameters):
                    rows = list(seq_of_parameters)
                    calls.append(len(rows))
                    return await self._base_cursor.executemany(sql, rows)

            yield _CursorProxy(cur)

    db.run_repository._write_transaction_cursor_provider = _wrapped_write_transaction
    samples = [sensor_frame_from_mapping({"i": i, "x": 0.1}) for i in range(700)]
    db.run_repository.append_samples("run-1", samples)
    assert sum(calls) == 700
    assert max(calls) <= 256
    assert len(calls) >= 3


def test_list_runs_includes_recorded_car_name(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    create_recording_run(db, "run-car", active_car_snapshot={"name": "Track Car"})

    run = db.run_repository.list_runs()[0]

    assert run.car_name == "Track Car"


def test_history_db_thread_safe_appends(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    create_recording_run(db, "run-2")

    def _append(start: int) -> None:
        batch = [sensor_frame_from_mapping({"i": start + i}) for i in range(50)]
        db.run_repository.append_samples("run-2", batch)

    with ThreadPoolExecutor(max_workers=4) as pool:
        for offset in range(0, 400, 50):
            pool.submit(_append, offset)

    assert len(db.run_repository.get_run_samples("run-2")) == 400


def test_append_samples_rejects_non_recording_runs(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run("run-guard", "2026-01-01T00:00:00Z", _metadata("run-guard"))

    written = db.run_repository.append_samples("run-guard", [sensor_frame_from_mapping({"i": 1})])
    assert written == 1

    db.run_repository.finalize_run("run-guard", "2026-01-01T00:10:00Z")
    rejected = db.run_repository.append_samples("run-guard", [sensor_frame_from_mapping({"i": 2})])

    assert rejected == 0
    run = db.run_repository.get_run("run-guard")
    assert run is not None
    assert run.status.value == "analyzing"
    assert run.sample_count == 1
    assert len(db.run_repository.get_run_samples("run-guard")) == 1


def test_close_uses_lock_and_clears_connection(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    events: list[str] = []

    class RecordingLock:
        def __init__(self, label: str) -> None:
            self._label = label

        def __enter__(self) -> None:
            events.append(f"{self._label}-enter")
            return None

        def __exit__(self, exc_type, exc, tb) -> bool:
            events.append(f"{self._label}-exit")
            return False

    db.lifecycle._lock = RecordingLock("write")  # type: ignore[assignment]
    db.lifecycle._read_lock = RecordingLock("read")  # type: ignore[assignment]

    db.lifecycle.close()

    assert events == ["write-enter", "write-exit", "read-enter", "read-exit"]
    assert db.lifecycle._conn is None
    assert db.lifecycle._read_conn is None


def test_schema_version_ancient_no_migration_fails_fast(tmp_path: Path) -> None:
    """A DB with a very old version that has no migration path should raise."""
    db_path = tmp_path / "history.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="incompatible"):
        create_history_persistence_adapters(db_path)


def test_schema_version_future_fails_fast(tmp_path: Path) -> None:
    """A DB with a newer version than supported should raise (no downgrade)."""
    db_path = tmp_path / "history.db"
    # Create a valid current-version DB first so the physical schema is correct
    db = create_history_persistence_adapters(db_path)
    db.lifecycle.close()
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA user_version = 99")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="newer than supported"):
        create_history_persistence_adapters(db_path)


def test_iter_run_samples_batches(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run("run-3", "2026-01-01T00:00:00Z", _metadata("run-3"))
    db.run_repository.append_samples(
        "run-3", [sensor_frame_from_mapping({"i": i}) for i in range(11)]
    )
    batches = list(db.run_repository.iter_run_samples("run-3", batch_size=4))
    assert [len(batch) for batch in batches] == [4, 4, 3]


def test_list_runs_uses_incremental_sample_count(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run("run-4", "2026-01-01T00:00:00Z", _metadata("run-4"))
    db.run_repository.append_samples(
        "run-4",
        [
            sensor_frame_from_mapping({"i": 1}),
            sensor_frame_from_mapping({"i": 2}),
            sensor_frame_from_mapping({"i": 3}),
        ],
    )
    run = db.run_repository.list_runs()[0]
    assert run.sample_count == 3


def test_recover_stale_recording_runs_marks_error(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run("run-5", "2026-01-01T00:00:00Z", _metadata("run-5"))
    recovered = db.run_repository.recover_stale_recording_runs()
    assert recovered == 1
    run = db.run_repository.get_run("run-5")
    assert run is not None
    assert run.status.value == "error"
    assert "Recovered stale recording during startup at" in str(run.error_message)


def test_prune_terminal_runs_older_than_days_deletes_only_old_terminal_runs(
    tmp_path: Path,
) -> None:
    db = build_history_db(tmp_path)
    create_completed_run(db, "run-old-complete", analysis_overrides={"score": 10})
    create_error_run(db, "run-old-error", error_message="failed")
    create_completed_run(db, "run-recent-complete", analysis_overrides={"score": 20})
    create_recording_run(db, "run-recording")
    create_analyzing_run(db, "run-analyzing")

    old_timestamp = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    recent_timestamp = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    _execute_statements(
        db.lifecycle,
        (
            "UPDATE runs SET analysis_completed_at = ?, end_time_utc = ? WHERE run_id = ?",
            (old_timestamp, old_timestamp, "run-old-complete"),
        ),
        (
            "UPDATE runs SET analysis_completed_at = ?, end_time_utc = ? WHERE run_id = ?",
            (old_timestamp, old_timestamp, "run-old-error"),
        ),
        (
            "UPDATE runs SET analysis_completed_at = ?, end_time_utc = ? WHERE run_id = ?",
            (recent_timestamp, recent_timestamp, "run-recent-complete"),
        ),
        (
            "UPDATE runs SET created_at = ? WHERE run_id = ?",
            (old_timestamp, "run-recording"),
        ),
        (
            "UPDATE runs SET created_at = ?, end_time_utc = ? WHERE run_id = ?",
            (old_timestamp, old_timestamp, "run-analyzing"),
        ),
    )

    pruned = db.run_repository.prune_terminal_runs_older_than_days(7)

    assert pruned == 2
    assert db.run_repository.get_run("run-old-complete") is None
    assert db.run_repository.get_run("run-old-error") is None
    assert db.run_repository.get_run("run-recent-complete") is not None
    assert db.run_repository.get_run("run-recording") is not None
    assert db.run_repository.get_run("run-analyzing") is not None


def test_prune_terminal_runs_older_than_days_cascades_samples(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    create_recording_run(db, "run-prune")
    db.run_repository.append_samples(
        "run-prune", [sensor_frame_from_mapping({"i": i}) for i in range(3)]
    )
    db.run_repository.store_analysis(
        "run-prune", make_persisted_analysis(_analysis("run-prune", score=9))
    )

    old_timestamp = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    _execute_statements(
        db.lifecycle,
        (
            "UPDATE runs SET analysis_completed_at = ?, end_time_utc = ? WHERE run_id = ?",
            (old_timestamp, old_timestamp, "run-prune"),
        ),
    )

    pruned = db.run_repository.prune_terminal_runs_older_than_days(7)

    assert pruned == 1
    assert db.run_repository.get_run("run-prune") is None
    row = _fetch_one(
        db.lifecycle,
        "SELECT COUNT(*) FROM samples_v2 WHERE run_id = ?",
        ("run-prune",),
    )
    assert row is not None and row[0] == 0


def test_create_run_does_not_auto_recover_recording(tmp_path: Path) -> None:
    """create_run no longer auto-recovers stale recordings — startup does that."""
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run("run-old", "2026-01-01T00:00:00Z", _metadata("run-old"))
    # Second create should fail (unique constraint) — old run stays recording
    try:
        db.run_repository.create_run("run-old", "2026-01-01T00:01:00Z", _metadata("run-old"))
    except Exception:
        pass
    old_run = db.run_repository.get_run("run-old")
    assert old_run is not None and old_run.status.value == "recording"


def test_create_run_persists_case_id(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")

    db.run_repository.create_run(
        "run-case-create",
        "2026-01-01T00:00:00Z",
        _metadata("run-case-create"),
        case_id="case-123",
    )

    run = db.run_repository.get_run("run-case-create")
    assert run is not None
    assert run.case_id == "case-123"


def test_recover_stale_recording_logs_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run("run-old", "2026-01-01T00:00:00Z", _metadata("run-old"))
    with caplog.at_level(logging.WARNING):
        recovered = db.run_repository.recover_stale_recording_runs()
    assert recovered == 1
    run = db.run_repository.get_run("run-old")
    assert run is not None and run.status.value == "error"


def test_history_db_runs_startup_quick_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Path] = []
    original = SQLiteHistoryEngine._run_startup_quick_check_async

    async def _tracking(self: SQLiteHistoryEngine) -> None:
        calls.append(self.db_path)
        await original(self)

    monkeypatch.setattr(SQLiteHistoryEngine, "_run_startup_quick_check_async", _tracking)
    db = create_history_persistence_adapters(tmp_path / "history.db")
    try:
        assert calls == [tmp_path / "history.db"]
    finally:
        db.lifecycle.close()


def test_startup_quick_check_logs_corruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")

    class _FakeCursor:
        async def execute(self, sql: str) -> None:
            assert sql == "PRAGMA quick_check"

        async def fetchall(self) -> list[tuple[str]]:
            return [("row 7 missing from index",)]

    @contextmanager
    def _fake_cursor(_self: SQLiteHistoryEngine, *, commit: bool = True):
        yield _FakeCursor()

    monkeypatch.setattr(SQLiteHistoryEngine, "_cursor", _fake_cursor)
    with caplog.at_level(logging.CRITICAL):
        db.lifecycle._run_startup_quick_check()
    assert "quick_check reported corruption" in caplog.text
    assert "row 7 missing from index" in caplog.text
    assert db.lifecycle.corruption_detected is True
    assert db.lifecycle.corruption_details == "row 7 missing from index"
    db.lifecycle.close()


def test_startup_quick_check_reports_corruption_via_callback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reported: list[str] = []
    db = create_history_persistence_adapters(
        tmp_path / "history.db",
        corruption_reporter=reported.append,
    )

    class _FakeCursor:
        async def execute(self, sql: str) -> None:
            assert sql == "PRAGMA quick_check"

        async def fetchall(self) -> list[tuple[str]]:
            return [("row 7 missing from index",)]

    @contextmanager
    def _fake_cursor(_self: SQLiteHistoryEngine, *, commit: bool = True):
        yield _FakeCursor()

    monkeypatch.setattr(SQLiteHistoryEngine, "_cursor", _fake_cursor)
    db.lifecycle._run_startup_quick_check()
    assert reported == ["row 7 missing from index"]
    assert db.lifecycle.corruption_detected is True
    db.lifecycle.close()


def test_startup_quick_check_blocks_future_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run("run-corrupt", "2026-01-01T00:00:00Z", _metadata("run-corrupt"))

    class _FakeCursor:
        def execute(self, sql: str) -> None:
            assert sql == "PRAGMA quick_check"

        def fetchall(self) -> list[tuple[str]]:
            return [("row 7 missing from index",)]

    @contextmanager
    def _fake_cursor(_self: SQLiteHistoryEngine, *, commit: bool = True):
        yield _FakeCursor()

    monkeypatch.setattr(SQLiteHistoryEngine, "_cursor", _fake_cursor)
    db.lifecycle._run_startup_quick_check()

    with pytest.raises(sqlite3.DatabaseError, match="Writes are disabled"):
        db.run_repository.append_samples("run-corrupt", [sensor_frame_from_mapping({"i": 1})])
    with pytest.raises(sqlite3.DatabaseError, match="Writes are disabled"):
        db.run_repository.finalize_run("run-corrupt", "2026-01-01T00:10:00Z")

    run = db.run_repository.get_run("run-corrupt")
    assert run is not None
    assert run.sample_count == 0
    assert run.status.value == "recording"
    db.lifecycle.close()


def test_delete_run_cascades_samples(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run("run-del", "2026-01-01T00:00:00Z", _metadata("run-del"))
    db.run_repository.append_samples(
        "run-del", [sensor_frame_from_mapping({"i": i}) for i in range(5)]
    )
    assert len(db.run_repository.get_run_samples("run-del")) == 5

    db.run_repository.delete_run("run-del")

    row = _fetch_one(
        db.lifecycle,
        "SELECT COUNT(*) FROM samples_v2 WHERE run_id = ?",
        ("run-del",),
    )
    assert row is not None and row[0] == 0


def test_run_status_transitions(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")

    db.run_repository.create_run("run-st", "2026-01-01T00:00:00Z", _metadata("run-st"))
    assert db.run_repository.get_run("run-st").status.value == "recording"

    db.run_repository.finalize_run("run-st", "2026-01-01T00:10:00Z")
    assert db.run_repository.get_run("run-st").status.value == "analyzing"

    db.run_repository.store_analysis(
        "run-st", make_persisted_analysis(_analysis("run-st", score=42))
    )
    assert db.run_repository.get_run("run-st").status.value == "complete"

    db.run_repository.create_run("run-err", "2026-01-01T00:00:00Z", _metadata("run-err"))
    db.run_repository.finalize_run("run-err", "2026-01-01T00:10:00Z")
    db.run_repository.store_analysis_error("run-err", "something went wrong")
    assert db.run_repository.get_run("run-err").status.value == "error"


def test_store_analysis_allows_direct_recording_to_complete(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run(
        "run-recording", "2026-01-01T00:00:00Z", _metadata("run-recording")
    )

    analysis = _analysis("run-recording", score=42)
    stored = db.run_repository.store_analysis("run-recording", make_persisted_analysis(analysis))

    assert stored is True
    run = db.run_repository.get_run("run-recording")
    assert run is not None
    assert run.status.value == "complete"
    assert run.analysis == analysis


def test_append_samples_rolls_back_when_metadata_update_fails(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run("run-rollback", "2026-01-01T00:00:00Z", _metadata("run-rollback"))
    original_write_tx = db.run_repository._write_transaction_cursor_provider

    @asynccontextmanager
    async def _wrapped_write_transaction():
        async with original_write_tx() as cur:

            class _CursorProxy:
                def __init__(self, base_cursor):
                    self._base_cursor = base_cursor

                def __getattr__(self, name: str):
                    return getattr(self._base_cursor, name)

                async def execute(self, sql: str, params=()):
                    if "UPDATE runs SET sample_count = sample_count + ?" in sql:
                        raise sqlite3.OperationalError("simulated sample_count failure")
                    return await self._base_cursor.execute(sql, params)

            yield _CursorProxy(cur)

    db.run_repository._write_transaction_cursor_provider = _wrapped_write_transaction

    with pytest.raises(sqlite3.OperationalError, match="simulated sample_count failure"):
        db.run_repository.append_samples(
            "run-rollback",
            [sensor_frame_from_mapping({"i": 1}), sensor_frame_from_mapping({"i": 2})],
        )

    run = db.run_repository.get_run("run-rollback")
    assert run is not None
    assert run.sample_count == 0
    assert db.run_repository.get_run_samples("run-rollback") == []


def test_finalize_run_returns_false_when_already_analyzing(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run("run-finalize", "2026-01-01T00:00:00Z", _metadata("run-finalize"))

    assert (
        db.run_repository.finalize_run(
            "run-finalize",
            "2026-01-01T00:05:00Z",
            metadata=_metadata("run-finalize"),
        )
        is True
    )
    assert (
        db.run_repository.finalize_run(
            "run-finalize",
            "2026-01-01T00:06:00Z",
            metadata=_metadata("run-finalize"),
        )
        is False
    )


def test_finalize_run_persists_case_id(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run(
        "run-case-finalize", "2026-01-01T00:00:00Z", _metadata("run-case-finalize")
    )

    assert (
        db.run_repository.finalize_run(
            "run-case-finalize",
            "2026-01-01T00:05:00Z",
            metadata=_metadata("run-case-finalize"),
            case_id="case-456",
        )
        is True
    )

    run = db.run_repository.get_run("run-case-finalize")
    assert run is not None
    assert run.status.value == "analyzing"
    assert run.case_id == "case-456"


def test_analyzing_run_health_reports_oldest_age(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    create_analyzing_run(db, "run-an")

    health = db.run_repository.analyzing_run_health()

    assert health.analyzing_run_count == 1
    assert isinstance(health.analyzing_oldest_age_s, float)


def test_update_run_metadata_overwrites_stored_metadata(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run(
        "run-meta", "2026-01-01T00:00:00Z", _metadata("run-meta", tire_width_mm=245.0)
    )
    assert (
        db.run_repository.update_run_metadata(
            "run-meta", _metadata("run-meta", tire_width_mm=285.0)
        )
        is True
    )
    run = db.run_repository.get_run("run-meta")
    assert run is not None
    assert run.metadata.analysis_settings.tire_width_mm == 285.0


def test_append_empty_samples_is_noop(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run("run-empty", "2026-01-01T00:00:00Z", _metadata("run-empty"))
    db.run_repository.append_samples("run-empty", [sensor_frame_from_mapping({"i": 1})])
    db.run_repository.append_samples("run-empty", [])
    run = db.run_repository.list_runs()[0]
    assert run.sample_count == 1


def test_client_names_crud(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")

    assert db.client_name_repository.list_client_names() == {}

    db.client_name_repository.upsert_client_name("client-1", "Alice")
    db.client_name_repository.upsert_client_name("client-2", "Bob")
    names = db.client_name_repository.list_client_names()
    assert names == {"client-1": "Alice", "client-2": "Bob"}

    db.client_name_repository.upsert_client_name("client-1", "Alice Updated")
    assert db.client_name_repository.list_client_names()["client-1"] == "Alice Updated"

    assert db.client_name_repository.delete_client_name("client-2") is True
    assert db.client_name_repository.delete_client_name("client-2") is False
    assert "client-2" not in db.client_name_repository.list_client_names()


def test_read_only_operations_do_not_commit(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run("run-ro", "2026-01-01T00:00:00Z", _metadata("run-ro"))
    db.run_repository.append_samples(
        "run-ro",
        [
            sensor_frame_from_mapping({"i": 1}),
            sensor_frame_from_mapping({"i": 2}),
        ],
    )
    db.settings_snapshot_repository.set_settings_snapshot(_settings_snapshot())
    db.client_name_repository.upsert_client_name("client-1", "Alice")

    class _ConnProxy:
        def __init__(self, conn):
            self._conn = conn
            self.commit_calls = 0

        def __getattr__(self, name: str):
            return getattr(self._conn, name)

        def commit(self):
            self.commit_calls += 1
            return self._conn.commit()

    proxy = _ConnProxy(db.lifecycle._conn)
    db.lifecycle._conn = proxy

    _ = db.run_repository.get_run("run-ro")
    _ = db.run_repository.list_runs()
    _ = list(db.run_repository.iter_run_samples("run-ro", batch_size=1))
    _ = db.run_repository.get_run_metadata("run-ro")
    _ = db.run_repository.get_run("run-ro").analysis
    _ = db.run_repository.get_run("run-ro").status
    _ = db.run_repository.get_active_run_id()
    _ = db.settings_snapshot_repository.get_settings_snapshot()
    _ = db.client_name_repository.list_client_names()

    assert proxy.commit_calls == 0

    db.settings_snapshot_repository.set_settings_snapshot(_settings_snapshot())
    assert proxy.commit_calls == 1


def test_get_run_metadata_non_dict_json_returns_none_and_warns(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.run_repository.create_run("run-bad-meta", "2026-01-01T00:00:00Z", _metadata("run-bad-meta"))
    _execute_statements(
        db.lifecycle,
        (
            "UPDATE runs SET metadata_json = ? WHERE run_id = ?",
            ("[1, 2, 3]", "run-bad-meta"),
        ),
    )

    with caplog.at_level(logging.WARNING, logger="vibesensor.adapters.persistence.history_db"):
        result = db.run_repository.get_run_metadata("run-bad-meta")

    assert result is None
    assert "run-bad-meta" in caplog.text
    assert "metadata_json" in caplog.text


def test_close_is_idempotent(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.lifecycle.close()
    db.lifecycle.close()


def test_operations_after_close_raise(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    db.lifecycle.close()
    with pytest.raises(RuntimeError, match="closed"):
        db.run_repository.create_run("run-x", "2026-01-01T00:00:00Z", _metadata("run-x"))
