"""Tests for the database schema migration system."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from vibesensor.history_db import HistoryDB
from vibesensor.history_db._migrations import run_migrations
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
"""
    )
    conn.commit()
    conn.close()


def _insert_v4_run(db_path: Path, run_id: str) -> None:
    """Insert a test run into a v4 database."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO runs (run_id, status, start_time_utc, metadata_json, created_at) "
        "VALUES (?, 'recording', '2026-01-01T00:00:00Z', '{\"lang\": \"en\"}', "
        "'2026-01-01T00:00:00Z')",
        (run_id,),
    )
    conn.commit()
    conn.close()


# -- migration runner tests --------------------------------------------------


def test_v4_to_v5_migration_adds_columns(tmp_path: Path) -> None:
    """v4→v5 migration should add analysis tracking columns to runs table."""
    db_path = tmp_path / "history.db"
    _create_v4_database(db_path)

    conn = sqlite3.connect(str(db_path))
    run_migrations(conn, 4, 5)

    columns = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    assert "analysis_version" in columns
    assert "analysis_started_at" in columns
    assert "analysis_completed_at" in columns
    conn.close()


def test_v4_to_v5_migration_creates_samples_v2(tmp_path: Path) -> None:
    """v4→v5 migration should create the samples_v2 table."""
    db_path = tmp_path / "history.db"
    _create_v4_database(db_path)

    conn = sqlite3.connect(str(db_path))
    run_migrations(conn, 4, 5)

    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert "samples_v2" in tables
    conn.close()


def test_v4_to_v5_migration_preserves_existing_runs(tmp_path: Path) -> None:
    """v4→v5 migration should not lose existing run data."""
    db_path = tmp_path / "history.db"
    _create_v4_database(db_path)
    _insert_v4_run(db_path, "test-run-1")
    _insert_v4_run(db_path, "test-run-2")

    conn = sqlite3.connect(str(db_path))
    run_migrations(conn, 4, 5)

    rows = conn.execute("SELECT run_id FROM runs ORDER BY run_id").fetchall()
    assert [r[0] for r in rows] == ["test-run-1", "test-run-2"]
    conn.close()


def test_v4_to_v5_migration_updates_version(tmp_path: Path) -> None:
    """v4→v5 migration should update schema_meta version to '5'."""
    db_path = tmp_path / "history.db"
    _create_v4_database(db_path)

    conn = sqlite3.connect(str(db_path))
    run_migrations(conn, 4, 5)

    row = conn.execute("SELECT value FROM schema_meta WHERE key = 'version'").fetchone()
    assert row is not None
    assert row[0] == "5"
    conn.close()


def test_migration_invalid_direction_raises(tmp_path: Path) -> None:
    """Attempting to migrate to an older version should raise ValueError."""
    db_path = tmp_path / "history.db"
    _create_v4_database(db_path)

    conn = sqlite3.connect(str(db_path))
    with pytest.raises(ValueError, match="source must be older"):
        run_migrations(conn, 5, 4)
    conn.close()


def test_migration_same_version_raises(tmp_path: Path) -> None:
    """Migrating from a version to itself should raise ValueError."""
    db_path = tmp_path / "history.db"
    _create_v4_database(db_path)

    conn = sqlite3.connect(str(db_path))
    with pytest.raises(ValueError, match="source must be older"):
        run_migrations(conn, 5, 5)
    conn.close()


def test_missing_migration_step_raises(tmp_path: Path) -> None:
    """If no migration is registered for a step, RuntimeError should be raised."""
    db_path = tmp_path / "history.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO schema_meta (key, value) VALUES ('version', '2')")
    conn.commit()

    with pytest.raises(RuntimeError, match="No migration registered"):
        run_migrations(conn, 2, 5)
    conn.close()


# -- HistoryDB integration tests ---------------------------------------------


def test_historydb_opens_v4_database_after_migration(tmp_path: Path) -> None:
    """HistoryDB should successfully open an older database by migrating it."""
    db_path = tmp_path / "history.db"
    _create_v4_database(db_path)
    _insert_v4_run(db_path, "preserved-run")

    db = HistoryDB(db_path)

    # Verify migration happened: version is now current
    with db._cursor(commit=False) as cur:
        cur.execute("SELECT value FROM schema_meta WHERE key = 'version'")
        row = cur.fetchone()
    assert row is not None
    assert int(row[0]) == SCHEMA_VERSION

    # Verify existing data survived
    run = db.get_run("preserved-run")
    assert run is not None
    assert run["run_id"] == "preserved-run"

    db.close()


def test_historydb_creates_backup_before_migration(tmp_path: Path) -> None:
    """HistoryDB should back up the database file before migrating."""
    db_path = tmp_path / "history.db"
    _create_v4_database(db_path)

    db = HistoryDB(db_path)
    db.close()

    backup_path = db_path.with_suffix(".bak-v4")
    assert backup_path.exists()
    # The backup should be a valid v4 database
    conn = sqlite3.connect(str(backup_path))
    row = conn.execute("SELECT value FROM schema_meta WHERE key = 'version'").fetchone()
    assert row is not None
    assert row[0] == "4"
    conn.close()


def test_historydb_newer_version_raises(tmp_path: Path) -> None:
    """HistoryDB should refuse to open a database with a newer schema version."""
    db_path = tmp_path / "history.db"
    # Create a DB that already has the full v5 physical schema but is tagged
    # as a *newer* version so that _ensure_schema sees version > SCHEMA_VERSION.
    db = HistoryDB(db_path)  # creates a normal v5 DB
    db.close()

    # Bump the stored version above the current one
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE schema_meta SET value = ? WHERE key = 'version'",
        (str(SCHEMA_VERSION + 1),),
    )
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
    """An existing v5 database should not trigger migration or backup."""
    db = HistoryDB(tmp_path / "history.db")
    db.close()

    # Re-open — should be a no-op
    db2 = HistoryDB(tmp_path / "history.db")
    db2.close()

    backup = tmp_path / "history.bak-v5"
    assert not backup.exists()
