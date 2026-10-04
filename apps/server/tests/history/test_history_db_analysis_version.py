"""A stored analysis written by an unknown storage version is reported corrupt, not misread."""

from __future__ import annotations

from pathlib import Path

from test_support.history_db_lifecycle import make_run_metadata
from test_support.history_db_sql import execute_statements

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
