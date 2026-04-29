"""Lifecycle, corruption, and durable-state coverage for HistoryDB."""

from __future__ import annotations

import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
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

from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
from vibesensor.shared.boundaries.sensor_frames import sensor_frame_from_mapping


def _create_corrupted_history_db(tmp_path: Path, *, truncate_bytes: int = 100) -> Path:
    db_path = tmp_path / "history.db"
    db = create_history_persistence_adapters(db_path)
    db.run_repository.create_run("run-corrupt", "2026-01-01T00:00:00Z", _metadata("run-corrupt"))
    db.run_repository.append_samples(
        "run-corrupt",
        [sensor_frame_from_mapping({"i": i, "x": 0.1}) for i in range(1000)],
    )
    db.lifecycle.close()
    db_path.write_bytes(db_path.read_bytes()[:-truncate_bytes])
    return db_path


def test_append_samples_large_batch_persists_all_rows(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    create_recording_run(db, "run-1")
    samples = [sensor_frame_from_mapping({"i": i, "x": 0.1}) for i in range(700)]
    written = db.run_repository.append_samples("run-1", samples)

    assert written == 700
    run = db.run_repository.get_run("run-1")
    assert run is not None
    assert run.sample_count == 700
    assert len(db.run_repository.get_run_samples("run-1")) == 700


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


def test_close_then_reopen_preserves_persisted_state(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    db = create_history_persistence_adapters(db_path)
    db.run_repository.create_run("run-close", "2026-01-01T00:00:00Z", _metadata("run-close"))
    db.run_repository.append_samples(
        "run-close",
        [sensor_frame_from_mapping({"i": 1}), sensor_frame_from_mapping({"i": 2})],
    )
    db.settings_snapshot_repository.set_settings_snapshot(_settings_snapshot())
    db.client_name_repository.upsert_client_name("client-1", "Alice")
    db.lifecycle.close()

    reopened = create_history_persistence_adapters(db_path)
    try:
        run = reopened.run_repository.get_run("run-close")
        assert run is not None
        assert run.sample_count == 2
        assert reopened.client_name_repository.list_client_names() == {"client-1": "Alice"}
        assert reopened.settings_snapshot_repository.get_settings_snapshot() == _settings_snapshot()
    finally:
        reopened.lifecycle.close()


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


def test_startup_quick_check_logs_corruption(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    db_path = _create_corrupted_history_db(tmp_path)

    with caplog.at_level(
        logging.CRITICAL, logger="vibesensor.adapters.persistence.history_db._engine"
    ):
        db = create_history_persistence_adapters(db_path)
    try:
        assert "quick_check reported corruption" in caplog.text
        assert db.lifecycle.corruption_detected is True
        assert db.lifecycle.corruption_details is not None
        assert db.lifecycle.corruption_details in caplog.text
    finally:
        db.lifecycle.close()


def test_startup_quick_check_reports_corruption_via_callback(
    tmp_path: Path,
) -> None:
    reported: list[str] = []
    db_path = _create_corrupted_history_db(tmp_path)
    db = create_history_persistence_adapters(
        db_path,
        corruption_reporter=reported.append,
    )
    try:
        assert db.lifecycle.corruption_detected is True
        assert db.lifecycle.corruption_details is not None
        assert reported == [db.lifecycle.corruption_details]
    finally:
        db.lifecycle.close()


def test_startup_quick_check_blocks_future_writes(
    tmp_path: Path,
) -> None:
    db_path = _create_corrupted_history_db(tmp_path)
    db = create_history_persistence_adapters(db_path)

    try:
        with pytest.raises(sqlite3.DatabaseError, match="Writes are disabled"):
            db.run_repository.append_samples(
                "run-corrupt", [sensor_frame_from_mapping({"i": 1001})]
            )
        with pytest.raises(sqlite3.DatabaseError, match="Writes are disabled"):
            db.run_repository.finalize_run("run-corrupt", "2026-01-01T00:10:00Z")

        run = db.run_repository.get_run("run-corrupt")
        assert run is not None
        assert run.sample_count == 1000
        assert run.status.value == "recording"
    finally:
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
    _execute_statements(
        db.lifecycle,
        (
            """
            CREATE TRIGGER fail_sample_count_update
            BEFORE UPDATE OF sample_count ON runs
            WHEN NEW.sample_count > OLD.sample_count
            BEGIN
                SELECT RAISE(FAIL, 'simulated sample_count failure');
            END
            """,
            (),
        ),
    )

    with pytest.raises(sqlite3.IntegrityError, match="simulated sample_count failure"):
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
