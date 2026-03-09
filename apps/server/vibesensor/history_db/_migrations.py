"""Incremental schema migration support for HistoryDB.

Each migration function upgrades the database from one schema version to
the next.  The runner applies them sequentially inside a single
transaction so the upgrade is atomic.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from collections.abc import Callable
from pathlib import Path

LOGGER = logging.getLogger(__name__)

# Type alias: a migration function takes a cursor and performs DDL/DML.
MigrationFn = Callable[[sqlite3.Cursor], None]


# ---------------------------------------------------------------------------
# Migration registry
# ---------------------------------------------------------------------------
# All legacy migrations removed per no-backward-compat policy.
# Schema must be at the current version or a fresh DB is created.
# If a future schema change is needed, add the migration here.

_MIGRATIONS: dict[int, MigrationFn] = {}


# -- public helpers ----------------------------------------------------------


def backup_database(db_path: Path, from_version: int) -> Path:
    """Create a backup of the database file before migration.

    Returns the path to the backup file.
    """
    backup_path = db_path.with_suffix(f".bak-v{from_version}")
    shutil.copy2(db_path, backup_path)
    LOGGER.info("Backed up database to %s before migration", backup_path)
    return backup_path


def run_migrations(
    conn: sqlite3.Connection,
    from_version: int,
    to_version: int,
) -> None:
    """Apply all registered migrations from *from_version* to *to_version*.

    All steps run inside a single transaction so the upgrade is atomic.
    On failure the transaction is rolled back and the caller should fall
    back to the pre-migration backup.
    """
    if from_version >= to_version:
        raise ValueError(
            f"Cannot migrate from v{from_version} to v{to_version} "
            "(source must be older than target)"
        )

    cur = conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        for step in range(from_version, to_version):
            fn = _MIGRATIONS.get(step)
            if fn is None:
                raise RuntimeError(
                    f"No migration registered for v{step} → v{step + 1}. "
                    f"Cannot upgrade from schema v{from_version} to v{to_version}."
                )
            fn(cur)
        cur.execute(
            "UPDATE schema_meta SET value = ? WHERE key = 'version'",
            (str(to_version),),
        )
        conn.commit()
        LOGGER.info("Schema migration complete: v%d → v%d", from_version, to_version)
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
