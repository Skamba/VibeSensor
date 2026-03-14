"""Tests for the database schema versioning system."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from vibesensor.history_db import HistoryDB
from vibesensor.history_db._schema import SCHEMA_VERSION

# -- helpers -----------------------------------------------------------------


def _create_v4_database(db_path: Path) -> None:
    """Create a minimal v4 schema database for migration testing."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """\
CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO schema_meta (key, value) VALUES ('version', '4');

CREATE TABLE runs (
    run_id          TEXT PRIMARY KEY,
    status          TEXT NOT NULL DEFAULT 'recording',
    start_time_utc  TEXT NOT NULL,
    end_time_utc    TEXT,
    metadata_json   TEXT NOT NULL,
    analysis_json   TEXT,
    error_message   TEXT,
    sample_count    INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at);

CREATE TABLE settings_kv (
    key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL
);

CREATE TABLE client_names (
    client_id TEXT PRIMARY KEY, name TEXT NOT NULL, updated_at TEXT NOT NULL
);
""",
    )
    conn.commit()
    conn.close()


# -- HistoryDB integration tests ---------------------------------------------


def test_historydb_rejects_v4_database(tmp_path: Path) -> None:
    """HistoryDB should refuse to open an incompatible older database."""
    db_path = tmp_path / "history.db"
    _create_v4_database(db_path)

    with pytest.raises(RuntimeError, match="incompatible"):
        HistoryDB(db_path)


def test_historydb_newer_version_raises(tmp_path: Path) -> None:
    """HistoryDB should refuse to open a database with a newer schema version."""
    db_path = tmp_path / "history.db"
    db = HistoryDB(db_path)
    db.close()

    conn = sqlite3.connect(str(db_path))
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="Cannot downgrade"):
        HistoryDB(db_path)


def test_historydb_fresh_db_works_normally(tmp_path: Path) -> None:
    """A fresh database (no existing file) should work as before."""
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("r1", "2026-01-01T00:00:00Z", {"source": "test"})
    run = db.get_run("r1")
    assert run is not None
    assert run["run_id"] == "r1"
    db.close()


def test_historydb_current_version_no_migration(tmp_path: Path) -> None:
    """An existing current-version database should not trigger migration or backup."""
    db = HistoryDB(tmp_path / "history.db")
    db.close()

    db2 = HistoryDB(tmp_path / "history.db")
    db2.close()

    conn = sqlite3.connect(str(tmp_path / "history.db"))
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()

    assert version == SCHEMA_VERSION

    backup = tmp_path / f"history.bak-v{SCHEMA_VERSION}"
    assert not backup.exists()
