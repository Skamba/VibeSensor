# ruff: noqa: E402
from __future__ import annotations

"""Runtime quality-pass regressions (issues 20–24).

Covers:
  20 – ring buffer wraparound (processing)
  21 – _bounded_sample edge cases (api)
  22 – speed_unit persistence (settings_store)
  23 – iter_run_samples pagination correctness (history_db)
  24 – schema v2→v3 migration (history_db)
"""


import sqlite3
from math import pi
from pathlib import Path

import numpy as np
import pytest

from vibesensor.adapters.persistence.history_db import HistoryDB
from vibesensor.adapters.persistence.runlog import bounded_sample as _bounded_sample
from vibesensor.infra.config.settings_store import SettingsStore
from vibesensor.infra.processing import SignalProcessor

# -- shared helpers ----------------------------------------------------------


def _make_history_db(tmp_path: Path, name: str = "history.db") -> HistoryDB:
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
    db.create_run(run_id, "2026-01-01T00:00:00Z", {"src": "test"})
    db.append_samples(run_id, [{"t_s": float(i)} for i in range(n_samples)])
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
# Issue 21 – _bounded_sample edge cases
# ---------------------------------------------------------------------------


class TestBoundedSample:
    @pytest.mark.parametrize(
        ("n_items", "max_items", "total_hint", "exp_total", "exp_len", "exp_stride"),
        [
            pytest.param(5, 100, None, 5, 5, 1, id="small_input_no_halving"),
            pytest.param(10, 10, None, 10, 10, None, id="exact_limit"),
            pytest.param(0, 10, None, 0, 0, None, id="empty_input"),
        ],
    )
    def test_bounded_sample_basic(
        self,
        n_items: int,
        max_items: int,
        total_hint: int | None,
        exp_total: int,
        exp_len: int,
        exp_stride: int | None,
    ) -> None:
        items = [{"i": i} for i in range(n_items)]
        kwargs: dict = {"max_items": max_items}
        if total_hint is not None:
            kwargs["total_hint"] = total_hint
        kept, total, stride = _bounded_sample(iter(items), **kwargs)
        assert total == exp_total
        assert len(kept) == exp_len
        if exp_stride is not None:
            assert stride == exp_stride

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


# ---------------------------------------------------------------------------
# Issue 22 – speed_unit persistence round-trip
# ---------------------------------------------------------------------------


def test_speed_unit_persists_and_round_trips(tmp_path: Path) -> None:
    db = _make_history_db(tmp_path, "settings.db")
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
    with pytest.raises(ValueError, match="speed_unit must be one of"):
        store.set_speed_unit("mph")  # not a valid choice


# ---------------------------------------------------------------------------
# Issue 23 – iter_run_samples pagination correctness
# ---------------------------------------------------------------------------


def test_iter_run_samples_returns_all_rows(tmp_path: Path) -> None:
    total = 37
    db = _seeded_history_db(tmp_path, "r1", total)

    all_rows: list[dict] = []
    for batch in db.iter_run_samples("r1", batch_size=10):
        all_rows.extend(batch)
    assert len(all_rows) == total
    assert [r["t_s"] for r in all_rows] == [float(i) for i in range(total)]


def test_iter_run_samples_offset(tmp_path: Path) -> None:
    db = _seeded_history_db(tmp_path, "r2", 20)

    all_rows: list[dict] = []
    for batch in db.iter_run_samples("r2", batch_size=5, offset=10):
        all_rows.extend(batch)
    assert len(all_rows) == 10
    assert all_rows[0]["t_s"] == 10.0


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
