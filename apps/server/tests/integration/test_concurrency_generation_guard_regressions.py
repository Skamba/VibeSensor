"""Concurrency and generation-guard regressions.

Tests covering:
1. Auto-stop generation guard (prevents killing a freshly started session)
2. Atomic delete_run_if_safe (TOCTOU fix)
3. finalize_run with metadata atomicity
4. stop_recording / start_recording _finalize_run_locked return-value gating
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor
from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
from vibesensor.infra.processing import SignalProcessor
from vibesensor.infra.runtime.registry import ClientRegistry
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.use_cases.run import RunRecorder, RunRecorderConfig


def _make_logger(tmp_path: Path, **overrides):
    """Create a minimal RunRecorder + HistoryDB for concurrency tests."""
    db = create_history_persistence_adapters(tmp_path / "history.db")
    registry = ClientRegistry(db=db.client_name_repository)
    # Separate config fields from collaborator overrides.
    _CONFIG_FIELDS = frozenset(
        {
            "metrics_log_hz",
            "sensor_model",
            "default_sample_rate_hz",
            "fft_window_size_samples",
            "accel_scale_g_per_lsb",
            "persist_history_db",
            "no_data_timeout_s",
        },
    )
    config_overrides = {k: overrides.pop(k) for k in list(overrides) if k in _CONFIG_FIELDS}
    config = RunRecorderConfig(
        metrics_log_hz=config_overrides.get("metrics_log_hz", 10),
        sensor_model=config_overrides.get("sensor_model", "ADXL345"),
        default_sample_rate_hz=config_overrides.get("default_sample_rate_hz", 800),
        fft_window_size_samples=config_overrides.get("fft_window_size_samples", 256),
        persist_history_db=config_overrides.get("persist_history_db", False),
    )
    collab_defaults = {
        "registry": registry,
        "gps_monitor": GPSSpeedMonitor(gps_enabled=False),
        "processor": SignalProcessor(
            sample_rate_hz=800,
            waveform_seconds=5,
            waveform_display_hz=60,
            fft_n=256,
            spectrum_max_hz=200,
        ),
        "history_db": db.run_repository,
    }
    collab_defaults.update(overrides)
    return RunRecorder(config, **collab_defaults), db


def _metadata(run_id: str, **overrides: object) -> RunMetadata:
    payload: dict[str, object] = {
        "run_id": run_id,
        "start_time_utc": "2026-01-01T00:00:00Z",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 800,
        "feature_interval_s": 1.0,
        "source": "test",
    }
    payload.update(overrides)
    return run_metadata_from_mapping(payload)


# ---------------------------------------------------------------------------
# 1. Auto-stop generation guard
# ---------------------------------------------------------------------------


class TestAutoStopGenerationGuard:
    """stop_recording(_only_if_run_id=X) must be a no-op when session has
    already advanced past run X.
    """

    def test_stale_run_id_does_not_stop_new_session(self, tmp_path: Path) -> None:
        logger, db = _make_logger(tmp_path)
        logger.start_recording()
        old_run_id = logger._run_id
        assert old_run_id is not None

        # Simulate: user starts a brand-new session
        logger.start_recording()
        new_run_id = logger._run_id
        assert new_run_id is not None
        assert new_run_id != old_run_id

        # Auto-stop fires for the *old* run_id
        logger.stop_recording(_only_if_run_id=old_run_id)

        # New session must still be alive
        assert logger.enabled is True
        assert logger._run_id == new_run_id
        db.lifecycle.close()

    def test_matching_run_id_does_stop(self, tmp_path: Path) -> None:
        logger, db = _make_logger(tmp_path)
        logger.start_recording()
        run_id = logger._run_id
        assert isinstance(run_id, str) and len(run_id) > 0

        logger.stop_recording(_only_if_run_id=run_id)
        assert logger.enabled is False
        assert logger._run_id is None
        db.lifecycle.close()


# ---------------------------------------------------------------------------
# 2. Atomic delete_run_if_safe
# ---------------------------------------------------------------------------


class TestDeleteRunIfSafe:
    """Cover safe-delete outcomes for complete, active, analyzing, missing, and error runs."""

    def test_delete_complete_run(self, tmp_path: Path) -> None:
        db = create_history_persistence_adapters(tmp_path / "h.db")
        db.run_repository.create_run("r1", "2026-01-01T00:00:00Z", _metadata("r1"))
        db.run_repository.finalize_run("r1", "2026-01-01T00:05:00Z")
        db.run_repository.store_analysis("r1", make_persisted_analysis({"score": 1}))
        deleted, reason = db.run_repository.delete_run_if_safe("r1")
        assert deleted is True
        assert reason is None
        assert db.run_repository.get_run("r1") is None
        db.lifecycle.close()

    def test_refuse_recording(self, tmp_path: Path) -> None:
        db = create_history_persistence_adapters(tmp_path / "h.db")
        db.run_repository.create_run("r1", "2026-01-01T00:00:00Z", _metadata("r1"))
        deleted, reason = db.run_repository.delete_run_if_safe("r1")
        assert deleted is False
        assert reason == "active"
        assert db.run_repository.get_run("r1") is not None
        db.lifecycle.close()

    def test_refuse_analyzing(self, tmp_path: Path) -> None:
        db = create_history_persistence_adapters(tmp_path / "h.db")
        db.run_repository.create_run("r1", "2026-01-01T00:00:00Z", _metadata("r1"))
        db.run_repository.finalize_run("r1", "2026-01-01T00:05:00Z")
        deleted, reason = db.run_repository.delete_run_if_safe("r1")
        assert deleted is False
        assert reason == "analyzing"
        db.lifecycle.close()

    def test_not_found(self, tmp_path: Path) -> None:
        db = create_history_persistence_adapters(tmp_path / "h.db")
        deleted, reason = db.run_repository.delete_run_if_safe("nonexistent")
        assert deleted is False
        assert reason == "not_found"
        db.lifecycle.close()

    def test_delete_error_run(self, tmp_path: Path) -> None:
        db = create_history_persistence_adapters(tmp_path / "h.db")
        db.run_repository.create_run("r1", "2026-01-01T00:00:00Z", _metadata("r1"))
        db.run_repository.store_analysis_error("r1", "boom")
        deleted, reason = db.run_repository.delete_run_if_safe("r1")
        assert deleted is True
        assert reason is None
        db.lifecycle.close()


# ---------------------------------------------------------------------------
# 3. finalize_run with metadata atomicity
# ---------------------------------------------------------------------------


class TestFinalizeRunWithMetadata:
    """Cover metadata updates on finalize_run and the no-op path after status changes."""

    def test_atomic_metadata_and_status(self, tmp_path: Path) -> None:
        db = create_history_persistence_adapters(tmp_path / "h.db")
        db.run_repository.create_run("r1", "2026-01-01T00:00:00Z", _metadata("r1"))
        new_meta = _metadata("r1", end_time_utc="2026-01-01T00:05:00Z")
        db.run_repository.finalize_run("r1", "2026-01-01T00:05:00Z", metadata=new_meta)
        run = db.run_repository.get_run("r1")
        assert run is not None
        assert run.status.value == "analyzing"
        assert run.end_time_utc == "2026-01-01T00:05:00Z"
        db.lifecycle.close()

    def test_only_recording_transitions(self, tmp_path: Path) -> None:
        db = create_history_persistence_adapters(tmp_path / "h.db")
        db.run_repository.create_run("r1", "2026-01-01T00:00:00Z", _metadata("r1"))
        db.run_repository.finalize_run("r1", "2026-01-01T00:05:00Z")
        # Already analyzing — second finalize with metadata should be no-op
        db.run_repository.finalize_run("r1", "2026-01-01T00:10:00Z", metadata=_metadata("r1"))
        run = db.run_repository.get_run("r1")
        assert run is not None
        assert run.status.value == "analyzing"
        assert run.end_time_utc == "2026-01-01T00:05:00Z"
        db.lifecycle.close()


# ---------------------------------------------------------------------------
# 4. _finalize_run_locked return value gates analysis scheduling
# ---------------------------------------------------------------------------


class TestFinalizeReturnGatesAnalysis:
    """When _finalize_run_locked fails, stop_recording still schedules analysis.

    store_analysis handles the RECORDING→COMPLETE bypass path, so analysis
    should proceed even if the RECORDING→ANALYZING transition fails.
    """

    def test_analysis_scheduled_despite_finalize_failure(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        logger, db = _make_logger(
            tmp_path,
            persist_history_db=True,
            language_reader=SimpleNamespace(language="en"),
        )

        logger.start_recording()
        run_id = logger._run_id
        assert isinstance(run_id, str) and len(run_id) > 0

        # Simulate a run that created history and wrote samples
        db.run_repository.create_run(run_id, "2026-01-01T00:00:00Z", _metadata(run_id))
        logger._persistence.history_run_created = True
        logger._persistence.written_sample_count = 5

        # Sabotage finalize_run to simulate a DB crash
        monkeypatch.setattr(
            type(db.run_repository),
            "finalize_run",
            lambda _self, *a, **kw: (_ for _ in ()).throw(sqlite3.OperationalError("disk gone")),
        )

        schedule_calls: list[str] = []
        monkeypatch.setattr(
            logger,
            "schedule_post_analysis",
            lambda rid: schedule_calls.append(rid),
        )

        logger.stop_recording()
        # Analysis IS scheduled despite finalize failure — store_analysis
        # handles the RECORDING → COMPLETE bypass.
        assert schedule_calls == [run_id], (
            f"Expected analysis to be scheduled for {run_id}, got: {schedule_calls}"
        )
        db.lifecycle.close()
