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


class TestFinalizeRunWithMetadata:
    def test_atomic_metadata_and_status(self, tmp_path: Path) -> None:
        db = HistoryDB(tmp_path / "h.db")
        db.create_run("r1", "2026-01-01T00:00:00Z", {"run_id": "r1"})
        new_meta = {"run_id": "r1", "end_time_utc": "2026-01-01T00:05:00Z", "extra": "val"}
        db.finalize_run_with_metadata("r1", "2026-01-01T00:05:00Z", new_meta)
        run = db.get_run("r1")
        assert run is not None
        assert run["status"] == "analyzing"
        assert run["end_time_utc"] == "2026-01-01T00:05:00Z"
        metadata = run.get("metadata", {})
        assert metadata.get("extra") == "val"
        db.close()

    def test_only_recording_transitions(self, tmp_path: Path) -> None:
        db = HistoryDB(tmp_path / "h.db")
        db.create_run("r1", "2026-01-01T00:00:00Z", {"run_id": "r1"})
        db.finalize_run("r1", "2026-01-01T00:05:00Z")
        # Already analyzing — second finalize_with_metadata should be no-op
        db.finalize_run_with_metadata("r1", "2026-01-01T00:10:00Z", {"extra": "v2"})
        run = db.get_run("r1")
        assert run is not None
        assert run["status"] == "analyzing"
        assert run["end_time_utc"] == "2026-01-01T00:05:00Z"
        db.close()
