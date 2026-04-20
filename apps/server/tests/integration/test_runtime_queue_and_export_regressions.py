"""Runtime queue/history tracking and export-filter regressions."""

from __future__ import annotations

from pathlib import Path

from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
from vibesensor.infra.processing import SignalProcessor


# ---------------------------------------------------------------------------
# Fix 1 – SQLite busy_timeout is set
# ---------------------------------------------------------------------------
class TestSQLiteBusyTimeout:
    """Verify HistoryDB configures a nonzero SQLite busy timeout on connect."""

    def test_busy_timeout_is_set(self, tmp_path: Path) -> None:
        """HistoryDB must set PRAGMA busy_timeout to avoid immediate SQLITE_BUSY."""
        db = create_history_persistence_adapters(tmp_path / "test.db")
        try:
            result = db.lifecycle._conn.execute("PRAGMA busy_timeout").fetchone()
            assert result is not None
            assert result[0] == 5000
        finally:
            db.lifecycle.close()


# ---------------------------------------------------------------------------
# Fix 2 – flush_client_buffer bumps ingest_generation
# ---------------------------------------------------------------------------
class TestFlushBumpsGeneration:
    """Verify flush_client_buffer invalidates cached metrics via generation bumps."""

    def test_flush_increments_ingest_generation(self) -> None:
        """Flushing a buffer must bump ingest_generation to invalidate stale caches."""
        proc = SignalProcessor(
            sample_rate_hz=400,
            waveform_seconds=2,
            waveform_display_hz=50,
            fft_n=512,
        )
        with proc._store.lock:
            buf = proc._store._registry._get_or_create_unlocked("sensor-1")
        buf.ingest_generation = 5
        buf.count = 10  # pretend some data
        proc.flush_client_buffer("sensor-1")
        assert buf.ingest_generation == 6
