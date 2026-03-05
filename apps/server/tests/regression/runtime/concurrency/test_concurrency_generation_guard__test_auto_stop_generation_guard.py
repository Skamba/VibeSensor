"""Concurrency and generation-guard regressions.

Tests covering:
1. Auto-stop generation guard (prevents killing a freshly started session)
2. Atomic delete_run_if_safe (TOCTOU fix)
3. finalize_run_with_metadata atomicity
4. stop_logging / start_logging _finalize_run_locked return-value gating
"""

from __future__ import annotations

from pathlib import Path

from vibesensor.analysis_settings import AnalysisSettingsStore
from vibesensor.gps_speed import GPSSpeedMonitor
from vibesensor.history_db import HistoryDB
from vibesensor.metrics_log import MetricsLogger
from vibesensor.processing import SignalProcessor
from vibesensor.registry import ClientRegistry


def _make_logger(tmp_path: Path, **overrides):
    """Create a minimal MetricsLogger + HistoryDB for concurrency tests."""
    db = HistoryDB(tmp_path / "history.db")
    registry = ClientRegistry(db=db)
    defaults = dict(
        enabled=False,
        log_path=tmp_path / "metrics.jsonl",
        metrics_log_hz=10,
        registry=registry,
        gps_monitor=GPSSpeedMonitor(gps_enabled=False),
        processor=SignalProcessor(
            sample_rate_hz=800,
            waveform_seconds=5,
            waveform_display_hz=60,
            fft_n=256,
            spectrum_max_hz=200,
        ),
        analysis_settings=AnalysisSettingsStore(),
        sensor_model="ADXL345",
        default_sample_rate_hz=800,
        fft_window_size_samples=256,
        history_db=db,
        persist_history_db=False,
    )
    defaults.update(overrides)
    return MetricsLogger(**defaults), db


class TestAutoStopGenerationGuard:
    """stop_logging(_only_if_generation=N) must be a no-op when session has
    already advanced past generation N."""

    def test_stale_generation_does_not_stop_new_session(self, tmp_path: Path) -> None:
        logger, db = _make_logger(tmp_path)
        logger.start_logging()
        old_gen = logger._session_generation
        old_run_id = logger._run_id
        assert old_run_id is not None

        # Simulate: user starts a brand-new session
        logger.start_logging()
        new_gen = logger._session_generation
        new_run_id = logger._run_id
        assert new_run_id is not None
        assert new_gen > old_gen

        # Auto-stop fires for the *old* generation
        logger.stop_logging(_only_if_generation=old_gen)

        # New session must still be alive
        assert logger.enabled is True
        assert logger._run_id == new_run_id
        db.close()

    def test_matching_generation_does_stop(self, tmp_path: Path) -> None:
        logger, db = _make_logger(tmp_path)
        logger.start_logging()
        gen = logger._session_generation

        logger.stop_logging(_only_if_generation=gen)
        assert logger.enabled is False
        assert logger._run_id is None
        db.close()
