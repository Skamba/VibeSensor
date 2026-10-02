"""Runtime quality-pass regressions (issues 20–24).

Covers:
  20 – ring buffer wraparound (processing)
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
from test_support.history_db_lifecycle import make_run_metadata as _metadata
from test_support.settings_services import build_settings_services

from vibesensor.adapters.persistence.history_db._history_db import HistoryDB
from vibesensor.infra.processing.processor import SignalProcessor
from vibesensor.shared.boundaries.sensor_frames.mapping import sensor_frame_from_mapping
from vibesensor.shared.types.sensor_frame import SensorFrame

# -- shared helpers ----------------------------------------------------------


def _make_history_db(
    tmp_path: Path,
    name: str = "history.db",
) -> HistoryDB:
    return HistoryDB(tmp_path / name)


def _seeded_history_db(
    tmp_path: Path,
    run_id: str,
    n_samples: int,
    *,
    name: str = "history.db",
) -> HistoryDB:
    """Create a HistoryDB with one run containing *n_samples* rows."""
    db = _make_history_db(tmp_path, name)
    db.create_run(run_id, "2026-01-01T00:00:00Z", _metadata(run_id, src="test"))
    db.append_samples(
        run_id,
        [sensor_frame_from_mapping({"t_s": float(i)}) for i in range(n_samples)],
    )
    return db


def _make_tone_chunk(freq_hz: float, n_samples: int, sample_rate_hz: int) -> np.ndarray:
    """Return an (N, 3) float32 chunk with a sine tone on the X axis."""
    t = np.arange(n_samples, dtype=np.float64) / sample_rate_hz
    x = (0.5 * np.sin(2 * pi * freq_hz * t)).astype(np.float32)
    zeros = np.zeros_like(x)
    return np.stack([x, zeros, zeros], axis=1)


# ---------------------------------------------------------------------------
# Issue 20 – ring buffer wraparound
# ---------------------------------------------------------------------------


def test_ring_buffer_wraparound_returns_correct_latest_data() -> None:
    """Ingest more samples than the buffer capacity and verify the
    latest window returns the *most recent* data, not early data.
    """
    sample_rate_hz = 800
    processor = SignalProcessor(
        sample_rate_hz=sample_rate_hz,
        waveform_seconds=2,  # capacity = 800 * 2 = 1600 samples
        waveform_display_hz=100,
        fft_n=1024,
        spectrum_max_hz=200,
    )

    # Phase 1 – fill with a 10 Hz tone (2400 samples → wraps at 1600)
    processor.ingest(
        "c1",
        _make_tone_chunk(10.0, 2400, sample_rate_hz),
        sample_rate_hz=sample_rate_hz,
    )

    # Phase 2 – overwrite with a 50 Hz tone (another 2400 samples)
    processor.ingest(
        "c1",
        _make_tone_chunk(50.0, 2400, sample_rate_hz),
        sample_rate_hz=sample_rate_hz,
    )

    metrics = processor.compute_metrics("c1", sample_rate_hz=sample_rate_hz)
    peaks = metrics["combined"]["peaks"]
    # The dominant peak should now be around 50 Hz (the most-recent data),
    # not 10 Hz (the old, overwritten data).
    dominant_hz = max(peaks, key=lambda p: float(p["amp"]))["hz"]
    assert abs(float(dominant_hz) - 50.0) < 5.0, f"expected ~50 Hz peak, got {dominant_hz}"


# ---------------------------------------------------------------------------
# Issue 22 – speed_unit persistence round-trip
# ---------------------------------------------------------------------------


def test_speed_unit_persists_and_round_trips(tmp_path: Path) -> None:
    db = _make_history_db(tmp_path, "settings.db")
    try:
        services = build_settings_services(db=db)

        # Default
        assert services.ui_preferences.speed_unit == "kmh"

        # Change to mps
        services.ui_preferences.set_speed_unit("mps")
        assert services.ui_preferences.speed_unit == "mps"

        # Reload from DB
        services2 = build_settings_services(db=db)
        assert services2.ui_preferences.speed_unit == "mps"

        # Invalid falls back
        with pytest.raises(ValueError, match="speed_unit must be one of"):
            services.ui_preferences.set_speed_unit("mph")  # not a valid choice
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Issue 23 – iter_run_samples pagination correctness
# ---------------------------------------------------------------------------


def test_iter_run_samples_returns_all_rows(tmp_path: Path) -> None:
    total = 37
    db = _seeded_history_db(tmp_path, "r1", total)
    try:
        all_rows: list[SensorFrame] = []
        for batch in db.iter_run_samples("r1", batch_size=10):
            all_rows.extend(batch)
        assert len(all_rows) == total
        assert [r.t_s for r in all_rows] == [float(i) for i in range(total)]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Issue 24 – schema v2→v3 migration
# ---------------------------------------------------------------------------


def test_old_schema_version_raises(tmp_path: Path) -> None:
    """Opening a DB with an older schema version should raise RuntimeError."""
    db_path = tmp_path / "history.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA user_version = 2")
    conn.executescript(
        """\
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
""",
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="incompatible"):
        HistoryDB(db_path)
