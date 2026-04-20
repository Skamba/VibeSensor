"""HistoryDB index/query-plan regression coverage."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters


def _query_plan_details(db_path: Path, sql: str) -> list[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return [str(row[3]) for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}")]
    finally:
        conn.close()


def test_history_db_status_created_at_queries_use_composite_index(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    db = create_history_persistence_adapters(db_path)
    db.lifecycle.close()

    latest_recording_plan = _query_plan_details(
        db_path,
        "SELECT run_id FROM runs WHERE status = 'recording' ORDER BY created_at DESC LIMIT 1",
    )
    analyzing_runs_plan = _query_plan_details(
        db_path,
        "SELECT run_id FROM runs WHERE status = 'analyzing' ORDER BY created_at ASC LIMIT 1000",
    )

    assert any("idx_runs_status_created_at" in detail for detail in latest_recording_plan)
    assert any("idx_runs_status_created_at" in detail for detail in analyzing_runs_plan)
    assert all("USE TEMP B-TREE FOR ORDER BY" not in detail for detail in latest_recording_plan)
    assert all("USE TEMP B-TREE FOR ORDER BY" not in detail for detail in analyzing_runs_plan)
