"""Cycle 4 — concurrency/race-condition audit fixes.

Tests covering:
1. Auto-stop generation guard (prevents killing a freshly started session)
2. Atomic delete_run_if_safe (TOCTOU fix)
3. finalize_run_with_metadata atomicity
4. stop_logging / start_logging _finalize_run_locked return-value gating
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vibesensor.history_db import HistoryDB

# ---------------------------------------------------------------------------
# 1. Auto-stop generation guard
# ---------------------------------------------------------------------------


class TestAutoStopGenerationGuard:
    """stop_logging(_only_if_generation=N) must be a no-op when session has
    already advanced past generation N."""

    def _make_logger(self, tmp_path: Path):
        from vibesensor.analysis_settings import AnalysisSettingsStore
        from vibesensor.gps_speed import GPSSpeedMonitor
        from vibesensor.metrics_log import MetricsLogger
        from vibesensor.processing import SignalProcessor
        from vibesensor.registry import ClientRegistry

        db = HistoryDB(tmp_path / "history.db")
        registry = ClientRegistry(db=db)
        return MetricsLogger(
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
        ), db

    def test_stale_generation_does_not_stop_new_session(self, tmp_path: Path) -> None:
        logger, db = self._make_logger(tmp_path)
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
        logger, db = self._make_logger(tmp_path)
        logger.start_logging()
        gen = logger._session_generation

        logger.stop_logging(_only_if_generation=gen)
        assert logger.enabled is False
        assert logger._run_id is None
        db.close()


# ---------------------------------------------------------------------------
# 2. Atomic delete_run_if_safe
# ---------------------------------------------------------------------------


class TestDeleteRunIfSafe:
    def test_delete_complete_run(self, tmp_path: Path) -> None:
        db = HistoryDB(tmp_path / "h.db")
        db.create_run("r1", "2026-01-01T00:00:00Z", {"run_id": "r1"})
        db.finalize_run("r1", "2026-01-01T00:05:00Z")
        db.store_analysis("r1", {"score": 1})
        deleted, reason = db.delete_run_if_safe("r1")
        assert deleted is True
        assert reason is None
        assert db.get_run("r1") is None
        db.close()

    def test_refuse_recording(self, tmp_path: Path) -> None:
        db = HistoryDB(tmp_path / "h.db")
        db.create_run("r1", "2026-01-01T00:00:00Z", {"run_id": "r1"})
        deleted, reason = db.delete_run_if_safe("r1")
        assert deleted is False
        assert reason == "active"
        assert db.get_run("r1") is not None
        db.close()

    def test_refuse_analyzing(self, tmp_path: Path) -> None:
        db = HistoryDB(tmp_path / "h.db")
        db.create_run("r1", "2026-01-01T00:00:00Z", {"run_id": "r1"})
        db.finalize_run("r1", "2026-01-01T00:05:00Z")
        deleted, reason = db.delete_run_if_safe("r1")
        assert deleted is False
        assert reason == "analyzing"
        db.close()

    def test_not_found(self, tmp_path: Path) -> None:
        db = HistoryDB(tmp_path / "h.db")
        deleted, reason = db.delete_run_if_safe("nonexistent")
        assert deleted is False
        assert reason == "not_found"
        db.close()

    def test_delete_error_run(self, tmp_path: Path) -> None:
        db = HistoryDB(tmp_path / "h.db")
        db.create_run("r1", "2026-01-01T00:00:00Z", {"run_id": "r1"})
        db.store_analysis_error("r1", "boom")
        deleted, reason = db.delete_run_if_safe("r1")
        assert deleted is True
        assert reason is None
        db.close()


# ---------------------------------------------------------------------------
# 3. finalize_run_with_metadata atomicity
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 4. _finalize_run_locked return value gates analysis scheduling
# ---------------------------------------------------------------------------


class TestFinalizeReturnGatesAnalysis:
    """When _finalize_run_locked fails, stop_logging must NOT schedule analysis."""

    def test_analysis_not_scheduled_when_finalize_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vibesensor.analysis_settings import AnalysisSettingsStore
        from vibesensor.gps_speed import GPSSpeedMonitor
        from vibesensor.metrics_log import MetricsLogger
        from vibesensor.processing import SignalProcessor
        from vibesensor.registry import ClientRegistry

        db = HistoryDB(tmp_path / "h.db")
        registry = ClientRegistry(db=db)
        logger = MetricsLogger(
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
