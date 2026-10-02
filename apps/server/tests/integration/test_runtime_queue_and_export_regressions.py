"""Runtime queue/history tracking and export-filter regressions."""

from __future__ import annotations

from pathlib import Path

from test_support.history_db_sql import fetch_one

from vibesensor.history.history_db import HistoryDB


# ---------------------------------------------------------------------------
# Fix 1 – SQLite busy_timeout is set
# ---------------------------------------------------------------------------
class TestSQLiteBusyTimeout:
    """Verify HistoryDB configures a nonzero SQLite busy timeout on connect."""

    def test_busy_timeout_is_set(self, tmp_path: Path) -> None:
        """HistoryDB must set PRAGMA busy_timeout to avoid immediate SQLITE_BUSY."""
        db = HistoryDB(tmp_path / "test.db")
        try:
            result = fetch_one(db, "PRAGMA busy_timeout")
            assert result is not None
            assert result[0] == 5000
        finally:
            db.close()
