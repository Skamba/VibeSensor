"""Concurrency and generation-guard regressions.

Tests covering:
1. Auto-stop generation guard (prevents killing a freshly started session)
2. Atomic delete_run_if_safe (TOCTOU fix)
3. finalize_run_with_metadata atomicity
4. stop_logging / start_logging _finalize_run_locked return-value gating
"""

from __future__ import annotations

from pathlib import Path

import pytest

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


class TestFinalizeReturnGatesAnalysis:
    """When _finalize_run_locked fails, stop_logging must NOT schedule analysis."""

    def test_analysis_not_scheduled_when_finalize_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logger, db = _make_logger(
            tmp_path,
            persist_history_db=True,
            language_provider=lambda: "en",
        )

        logger.start_logging()
        run_id = logger._run_id
        assert run_id is not None

        # Simulate a run that created history and wrote samples
        db.create_run(run_id, "2026-01-01T00:00:00Z", {"run_id": run_id})
        logger._history_run_created = True
        logger._written_sample_count = 5

        # Sabotage finalize_run_with_metadata to simulate a DB crash
        monkeypatch.setattr(
            db,
            "finalize_run_with_metadata",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("disk gone")),
        )

        schedule_calls: list[str] = []
        monkeypatch.setattr(
            logger,
            "_schedule_post_analysis",
            lambda rid: schedule_calls.append(rid),
        )

        logger.stop_logging()
        # Analysis must NOT have been scheduled because finalize failed
        assert schedule_calls == [], (
            f"Expected no analysis scheduling after finalize failure, got: {schedule_calls}"
        )
        db.close()
