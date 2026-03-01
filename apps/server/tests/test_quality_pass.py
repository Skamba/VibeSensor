"""Tests added by the quality-pass (issues 19–24).

Covers:
  19 – bad-client diagnostics skip (live_diagnostics)
  20 – ring buffer wraparound (processing)
  21 – _bounded_sample edge cases (api)
  22 – speed_unit persistence (settings_store)
  23 – iter_run_samples pagination correctness (history_db)
  24 – schema v2→v3 migration (history_db)
"""

from __future__ import annotations

import sqlite3
from math import pi
from pathlib import Path

import numpy as np
import pytest

from vibesensor.api import _bounded_sample
from vibesensor.history_db import HistoryDB
from vibesensor.live_diagnostics import LiveDiagnosticsEngine
from vibesensor.processing import SignalProcessor
from vibesensor.settings_store import SettingsStore

# ---------------------------------------------------------------------------
# Issue 19 – _detect_sensor_events skips bad clients rather than crashing
# ---------------------------------------------------------------------------


class TestDiagnosticsSkipsBadClients:
    """After the fix, a client with missing strength_metrics is silently
    skipped instead of raising ``ValueError``."""

    @staticmethod
    def _engine() -> LiveDiagnosticsEngine:
        return LiveDiagnosticsEngine()

    def test_missing_strength_metrics_is_skipped(self) -> None:
        engine = self._engine()
        good_payload: dict = {
            "strength_metrics": {
                "top_peaks": [{"hz": 10.0, "amp": 0.01, "vibration_strength_db": 5.0}],
            },
        }
        spectra = {"clients": {"good": good_payload, "bad": {"missing": True}}}
        # Should not raise
        events = engine._detect_sensor_events(
            speed_mps=10.0,
            clients=[{"id": "good"}, {"id": "bad"}],
            spectra=spectra,
            settings={},
        )
        # The good client is still processed; the bad one is silently skipped
        assert isinstance(events, list)
        assert len(events) >= 1, "Good client events should still be produced"

    def test_missing_top_peaks_is_skipped(self) -> None:
        engine = self._engine()
        spectra = {
            "clients": {
                "c1": {"strength_metrics": {"no_peaks_here": True}},
            }
        }
        events = engine._detect_sensor_events(
            speed_mps=10.0,
            clients=[{"id": "c1"}],
            spectra=spectra,
            settings={},
        )
        assert events == []


# ---------------------------------------------------------------------------
# Issue 20 – ring buffer wraparound
# ---------------------------------------------------------------------------


def test_ring_buffer_wraparound_returns_correct_latest_data() -> None:
    """Ingest more samples than the buffer capacity and verify the
    latest window returns the *most recent* data, not early data."""
    sample_rate_hz = 800
    processor = SignalProcessor(
        sample_rate_hz=sample_rate_hz,
        waveform_seconds=2,  # capacity = 800 * 2 = 1600 samples
        waveform_display_hz=100,
        fft_n=1024,
        spectrum_max_hz=200,
    )

    # Phase 1 – fill with a 10 Hz tone (2400 samples → wraps at 1600)
    n1 = 2400
    t1 = np.arange(n1, dtype=np.float64) / sample_rate_hz
    x1 = (0.5 * np.sin(2 * pi * 10.0 * t1)).astype(np.float32)
    chunk1 = np.stack([x1, np.zeros_like(x1), np.zeros_like(x1)], axis=1)
    processor.ingest("c1", chunk1, sample_rate_hz=sample_rate_hz)

    # Phase 2 – overwrite with a 50 Hz tone (another 2400 samples)
    n2 = 2400
    t2 = np.arange(n2, dtype=np.float64) / sample_rate_hz
    x2 = (0.5 * np.sin(2 * pi * 50.0 * t2)).astype(np.float32)
    chunk2 = np.stack([x2, np.zeros_like(x2), np.zeros_like(x2)], axis=1)
    processor.ingest("c1", chunk2, sample_rate_hz=sample_rate_hz)

    metrics = processor.compute_metrics("c1", sample_rate_hz=sample_rate_hz)
    peaks = metrics["combined"]["peaks"]
    # The dominant peak should now be around 50 Hz (the most-recent data),
    # not 10 Hz (the old, overwritten data).
    dominant_hz = max(peaks, key=lambda p: float(p["amp"]))["hz"]
    assert abs(float(dominant_hz) - 50.0) < 5.0, f"expected ~50 Hz peak, got {dominant_hz}"


# ---------------------------------------------------------------------------
# Issue 21 – _bounded_sample edge cases
# ---------------------------------------------------------------------------


class TestBoundedSample:
    def test_small_input_no_halving(self) -> None:
        items = [{"i": i} for i in range(5)]
        kept, total, stride = _bounded_sample(iter(items), max_items=100)
        assert total == 5
        assert stride == 1
        assert len(kept) == 5

    def test_exact_limit(self) -> None:
        items = [{"i": i} for i in range(10)]
        kept, total, stride = _bounded_sample(iter(items), max_items=10)
        assert total == 10
        assert len(kept) == 10

    def test_halving_reduces_count(self) -> None:
        items = [{"i": i} for i in range(200)]
        kept, total, stride = _bounded_sample(iter(items), max_items=50)
        assert total == 200
        assert len(kept) <= 50
        assert stride > 1

    def test_total_hint_avoids_halving(self) -> None:
        """With total_hint provided, stride is pre-computed."""
        items = [{"i": i} for i in range(200)]
        kept, total, stride = _bounded_sample(iter(items), max_items=50, total_hint=200)
        assert total == 200
        assert stride == 4
        assert len(kept) == 50

    def test_empty_input(self) -> None:
        kept, total, stride = _bounded_sample(iter([]), max_items=10)
        assert total == 0
        assert kept == []


# ---------------------------------------------------------------------------
# Issue 22 – speed_unit persistence round-trip
# ---------------------------------------------------------------------------


def test_speed_unit_persists_and_round_trips(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "settings.db")
    store = SettingsStore(db)

    # Default
    assert store.speed_unit == "kmh"

    # Change to mps
    store.set_speed_unit("mps")
    assert store.speed_unit == "mps"

    # Reload from DB
    store2 = SettingsStore(db)
    assert store2.speed_unit == "mps"

    # Invalid falls back
    with pytest.raises(ValueError):
        store.set_speed_unit("mph")  # not a valid choice


# ---------------------------------------------------------------------------
# Issue 23 – iter_run_samples pagination correctness
# ---------------------------------------------------------------------------


def test_iter_run_samples_returns_all_rows(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("r1", "2026-01-01T00:00:00Z", {"src": "test"})
    total = 37
    db.append_samples("r1", [{"i": i} for i in range(total)])

    all_rows: list[dict] = []
    for batch in db.iter_run_samples("r1", batch_size=10):
        all_rows.extend(batch)
    assert len(all_rows) == total
    assert [r["i"] for r in all_rows] == list(range(total))


def test_iter_run_samples_offset(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("r2", "2026-01-01T00:00:00Z", {"src": "test"})
    db.append_samples("r2", [{"i": i} for i in range(20)])

    all_rows: list[dict] = []
    for batch in db.iter_run_samples("r2", batch_size=5, offset=10):
        all_rows.extend(batch)
    assert len(all_rows) == 10
    assert all_rows[0]["i"] == 10


# ---------------------------------------------------------------------------
# Issue 24 – schema v2→v3 migration
# ---------------------------------------------------------------------------


def test_old_schema_version_raises(tmp_path: Path) -> None:
    """Opening a DB with an older schema version should raise RuntimeError."""
    db_path = tmp_path / "history.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """\
CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO schema_meta (key, value) VALUES ('version', '2');
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    start_time TEXT NOT NULL,
    end_time TEXT,
    status TEXT NOT NULL DEFAULT 'recording',
    error_message TEXT,
    metadata_json TEXT,
    analysis_json TEXT,
    created_at TEXT NOT NULL,
    sample_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    sample_json TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
"""
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="Unsupported history DB schema version 2"):
        HistoryDB(db_path)
