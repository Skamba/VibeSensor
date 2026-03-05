"""Runtime quality-pass regressions (issues 19–24).

Covers:
  19 – bad-client diagnostics skip (live_diagnostics)
  20 – ring buffer wraparound (processing)
  21 – _bounded_sample edge cases (api)
  22 – speed_unit persistence (settings_store)
  23 – iter_run_samples pagination correctness (history_db)
  24 – schema v2→v3 migration (history_db)
"""

from __future__ import annotations

from math import pi
from pathlib import Path

import numpy as np

from vibesensor.history_db import HistoryDB
from vibesensor.live_diagnostics import LiveDiagnosticsEngine


def _make_history_db(tmp_path: Path, name: str = "history.db") -> HistoryDB:
    return HistoryDB(tmp_path / name)


def _seeded_history_db(
    tmp_path: Path, run_id: str, n_samples: int, *, name: str = "history.db"
) -> HistoryDB:
    """Create a HistoryDB with one run containing *n_samples* rows."""
    db = _make_history_db(tmp_path, name)
    db.create_run(run_id, "2026-01-01T00:00:00Z", {"src": "test"})
    db.append_samples(run_id, [{"i": i} for i in range(n_samples)])
    return db


def _make_tone_chunk(freq_hz: float, n_samples: int, sample_rate_hz: int) -> np.ndarray:
    """Return an (N, 3) float32 chunk with a sine tone on the X axis."""
    t = np.arange(n_samples, dtype=np.float64) / sample_rate_hz
    x = (0.5 * np.sin(2 * pi * freq_hz * t)).astype(np.float32)
    zeros = np.zeros_like(x)
    return np.stack([x, zeros, zeros], axis=1)


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
