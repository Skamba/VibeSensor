"""HistoryDB backup-creation and index/query-plan regression coverage."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import vibesensor.adapters.persistence.history_db as history_db_module
from vibesensor.adapters.persistence.history_db import HistoryDB
from vibesensor.adapters.persistence.history_db._schema import SCHEMA_VERSION


def _query_plan_details(db_path: Path, sql: str) -> list[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return [str(row[3]) for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}")]
    finally:
        conn.close()


def test_history_db_status_created_at_queries_use_composite_index(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    db = HistoryDB(db_path)
    db.close()

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


def test_history_db_migration_backup_cleans_up_temp_file_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = HistoryDB(tmp_path / "history.db")
    created_temp_paths: list[Path] = []
    closed_backup_connections: list[bool] = []

    class _FailingBackupConnection:
        def execute(self, _sql: str) -> None:
            raise OSError("backup prep failed")

        def close(self) -> None:
            closed_backup_connections.append(True)

    def _fake_connect(
        path: str | Path,
        *args: object,
        **kwargs: object,
    ) -> _FailingBackupConnection:
        del args, kwargs
        created_temp_paths.append(Path(path))
        return _FailingBackupConnection()

    monkeypatch.setattr(history_db_module.sqlite3, "connect", _fake_connect)

    try:
        with pytest.raises(OSError, match="backup prep failed"):
            db._create_migration_backup(SCHEMA_VERSION)
    finally:
        db.close()

    assert closed_backup_connections == [True]
    assert len(created_temp_paths) == 1
    assert not created_temp_paths[0].exists()
    assert not list(tmp_path.glob(f"history.bak-v{SCHEMA_VERSION}.*.tmp"))
