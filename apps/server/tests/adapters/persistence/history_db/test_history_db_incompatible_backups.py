"""Focused incompatible-schema backup/export coverage for HistoryDB."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters


def test_schema_version_ancient_no_migration_creates_backup_and_summary_export(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "history.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            status TEXT,
            start_time_utc TEXT,
            created_at TEXT,
            metadata_json TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO runs (run_id, status, start_time_utc, created_at, metadata_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            "run-legacy",
            "complete",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
            json.dumps({"run_id": "run-legacy"}),
        ),
    )
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="incompatible"):
        create_history_persistence_adapters(db_path)
    backup_dir = tmp_path / "history-db-backups"
    backups = list(backup_dir.glob("history.incompatible-v1-unsupported-schema-*.db"))
    exports = list(
        backup_dir.glob("history.incompatible-v1-unsupported-schema-*.run-summaries.jsonl")
    )
    assert len(backups) == 1
    assert len(exports) == 1
    assert '"run_id":"run-legacy"' in exports[0].read_text(encoding="utf-8")


def test_schema_version_future_creates_backup_before_rejection(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    db = create_history_persistence_adapters(db_path)
    db.lifecycle.close()
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA user_version = 99")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="newer than supported"):
        create_history_persistence_adapters(db_path)
    backups = list(
        (tmp_path / "history-db-backups").glob("history.incompatible-v99-newer-schema-*.db")
    )
    assert len(backups) == 1
