"""SQLite-backed persistence for the VibeSensor server.

Stores run history (metadata, samples, analysis), application settings
and client names in a single file – lightweight enough for a
Raspberry Pi 3A+.

Schema v5 stores time-series samples as typed columns in ``samples_v2``,
providing fast write/read and compact storage on Raspberry Pi class
hardware.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from ._client_names import HistoryClientNamesMixin
from ._runs import ANALYSIS_SCHEMA_VERSION as ANALYSIS_SCHEMA_VERSION
from ._runs import HistoryRunStoreMixin
from ._runs import RunStatus as RunStatus
from ._schema import HistorySchemaMixin
from ._settings import HistorySettingsStoreMixin

LOGGER = logging.getLogger(__name__)


class HistoryDB(
    HistoryRunStoreMixin,
    HistorySettingsStoreMixin,
    HistoryClientNamesMixin,
    HistorySchemaMixin,
):
    """Thin wrapper around a SQLite database for run history."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = RLock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = sqlite3.connect(db_path, check_same_thread=False)
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA wal_autocheckpoint=500")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._ensure_schema()
        except Exception:
            self._conn.close()
            raise

    # -- lifecycle ------------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    @contextmanager
    def _cursor(self, *, commit: bool = True) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            if self._conn is None:
                raise RuntimeError("HistoryDB is closed")
            cur = self._conn.cursor()
            try:
                yield cur
                if commit:
                    self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    @contextmanager
    def write_transaction_cursor(self) -> Iterator[sqlite3.Cursor]:
        """Run a multi-step write sequence as one explicit transaction."""
        with self._lock:
            if self._conn is None:
                raise RuntimeError("HistoryDB is closed")
            cur = self._conn.cursor()
            try:
                cur.execute("BEGIN IMMEDIATE")
                yield cur
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    @contextmanager
    def read_transaction(self) -> Iterator[None]:
        """Hold a single read transaction across multi-step read operations."""
        with self._lock:
            if self._conn is None:
                raise RuntimeError("HistoryDB is closed")
            cur = self._conn.cursor()
            try:
                cur.execute("BEGIN")
                yield
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()
