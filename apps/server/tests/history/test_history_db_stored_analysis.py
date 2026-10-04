"""Stored analyses: unreadable ones are reported corrupt, completed ones are not overwritten."""

from __future__ import annotations

from pathlib import Path

from test_support.history_db_lifecycle import make_run_metadata
from test_support.history_db_sql import execute_statements
from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.history.history_db import HistoryDB


def test_get_run_marks_unknown_analysis_storage_version_corrupt(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("r1", "2026-01-01T00:00:00Z", make_run_metadata("r1"))
    db.finalize_run("r1", "2026-01-01T00:01:00Z")

    execute_statements(
        db,
        (
            "UPDATE runs SET analysis_json = ? WHERE run_id = ?",
            ('{"_schema_version": 99, "findings": []}', "r1"),
        ),
    )

    run = db.get_run("r1")
    assert run is not None
    assert run.analysis is None
    assert run.analysis_corrupt is True
    db.close()


# -- Post-analysis lifecycle tests (integration) ------------------------------


def test_get_run_marks_a_non_object_analysis_corrupt(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("r1", "2026-01-01T00:00:00Z", make_run_metadata("r1"))
    execute_statements(
        db,
        (
            "UPDATE runs SET status='complete', analysis_json=? WHERE run_id=?",
            ("[1,2,3]", "r1"),
        ),
    )

    run = db.get_run("r1")

    assert run is not None
    assert run.analysis is None
    assert run.analysis_corrupt is True
    db.close()


def test_a_late_analysis_error_does_not_overwrite_a_completed_run(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("r1", "2024-01-01T00:00:00", make_run_metadata("r1"))
    db.store_analysis("r1", make_persisted_analysis({"result": "ok"}))
    before = db.get_run("r1")

    db.store_analysis_error("r1", "spurious error")

    after = db.get_run("r1")
    assert before is not None and after is not None
    assert after.status.value == "complete"
    assert after.analysis == before.analysis
    db.close()
