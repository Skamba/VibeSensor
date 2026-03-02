"""Tests for history DB write-failure handling in MetricsLogger (issue #296).

Verifies that DB write failures are:
1. Exposed via status()['write_error']
2. Logged at the correct severity
3. Tracked with a consecutive failure counter
4. Samples are logged as dropped when history run creation persistently fails
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

from vibesensor.metrics_log import _MAX_HISTORY_CREATE_RETRIES, MetricsLogger

# -- Minimal fakes -----------------------------------------------------------


@dataclass(slots=True)
class _FakeRecord:
    client_id: str
    name: str
    sample_rate_hz: int
    latest_metrics: dict
    frames_total: int = 0
    frames_dropped: int = 0
    queue_overflow_drops: int = 0


class _FakeRegistry:
    def __init__(self) -> None:
        self._records = {
            "active": _FakeRecord(
                client_id="active",
                name="front-left",
                sample_rate_hz=800,
                latest_metrics={
                    "strength_metrics": {
                        "vibration_strength_db": 22.0,
                        "strength_bucket": "l2",
                        "top_peaks": [
                            {
                                "hz": 15.0,
                                "amp": 0.12,
                                "vibration_strength_db": 22.0,
                                "strength_bucket": "l2",
                            }
                        ],
                        "combined_spectrum_amp_g": [],
                    },
                    "combined": {"peaks": [{"hz": 15.0, "amp": 0.12}]},
                    "x": {"rms": 0.04, "p2p": 0.11, "peaks": [{"hz": 15.0, "amp": 0.12}]},
                    "y": {"rms": 0.03, "p2p": 0.10, "peaks": [{"hz": 16.0, "amp": 0.08}]},
                    "z": {"rms": 0.02, "p2p": 0.09, "peaks": [{"hz": 14.0, "amp": 0.07}]},
                },
            ),
        }

    def active_client_ids(self) -> list[str]:
        return ["active"]

    def get(self, client_id: str) -> _FakeRecord | None:
        return self._records.get(client_id)


class _FakeGPSMonitor:
    speed_mps = None
    effective_speed_mps = None
    override_speed_mps = None

    def resolve_speed(self):
        from vibesensor.gps_speed import SpeedResolution

        return SpeedResolution(speed_mps=None, fallback_active=False, source="none")


class _FakeProcessor:
    def latest_sample_xyz(self, client_id: str):
        return (0.01, 0.02, 0.03)

    def latest_sample_rate_hz(self, client_id: str):
        return 800

    def clients_with_recent_data(self, client_ids: list[str], max_age_s: float = 3.0) -> list[str]:
        return list(client_ids)


class _FakeAnalysisSettings:
    def snapshot(self) -> dict[str, float]:
        return {
            "tire_width_mm": 285.0,
            "tire_aspect_pct": 30.0,
            "rim_in": 21.0,
            "final_drive_ratio": 3.08,
            "current_gear_ratio": 0.64,
        }


def _make_logger(history_db, tmp_path: Path) -> MetricsLogger:
    return MetricsLogger(
        enabled=False,
        log_path=tmp_path / "metrics.jsonl",
        metrics_log_hz=2,
        registry=_FakeRegistry(),
        gps_monitor=_FakeGPSMonitor(),
        processor=_FakeProcessor(),
        analysis_settings=_FakeAnalysisSettings(),
        sensor_model="ADXL345",
        default_sample_rate_hz=800,
        fft_window_size_samples=1024,
        history_db=history_db,
    )


# -- Tests -------------------------------------------------------------------


class TestCreateRunFailureExposesWriteError:
    """When _ensure_history_run_created fails, write_error is visible in status."""

    def test_single_create_run_failure_sets_write_error(self, tmp_path: Path) -> None:
        db = MagicMock()
        db.create_run.side_effect = OSError("disk full")
        logger = _make_logger(db, tmp_path)

        logger.start_logging()
        snap = logger._session_snapshot()
        assert snap is not None
        run_id, start_utc, start_mono, generation = snap

        logger._ensure_history_run_created(run_id, start_utc, session_generation=generation)

        status = logger.status()
        assert status["write_error"] is not None
        assert "disk full" in status["write_error"]
        assert not logger._history_run_created

    def test_create_run_success_clears_write_error(self, tmp_path: Path) -> None:
        db = MagicMock()
        db.create_run.side_effect = [OSError("first fail"), None]
        logger = _make_logger(db, tmp_path)

        logger.start_logging()
        snap = logger._session_snapshot()
        assert snap is not None
        run_id, start_utc, start_mono, generation = snap

        # First call fails
        logger._ensure_history_run_created(run_id, start_utc, session_generation=generation)
        assert logger.status()["write_error"] is not None

        # Second call succeeds
        logger._ensure_history_run_created(run_id, start_utc, session_generation=generation)
        assert logger._history_run_created
        assert logger.status()["write_error"] is None


class TestPersistentCreateRunFailureStopsRetrying:
    """After _MAX_HISTORY_CREATE_RETRIES failures, stop retrying."""

    def test_gives_up_after_max_retries(self, tmp_path: Path) -> None:
        db = MagicMock()
        db.create_run.side_effect = OSError("persistent failure")
        logger = _make_logger(db, tmp_path)

        logger.start_logging()
        snap = logger._session_snapshot()
        assert snap is not None
        run_id, start_utc, _start_mono, generation = snap

        for _ in range(_MAX_HISTORY_CREATE_RETRIES + 3):
            logger._ensure_history_run_created(run_id, start_utc, session_generation=generation)

        # Should have been called exactly _MAX_HISTORY_CREATE_RETRIES times
        assert db.create_run.call_count == _MAX_HISTORY_CREATE_RETRIES
        assert logger._history_create_fail_count == _MAX_HISTORY_CREATE_RETRIES
        assert not logger._history_run_created
        assert logger.status()["write_error"] is not None

    def test_retry_counter_resets_on_new_session(self, tmp_path: Path) -> None:
        db = MagicMock()
        db.create_run.side_effect = OSError("fail")
        logger = _make_logger(db, tmp_path)

        logger.start_logging()
        snap = logger._session_snapshot()
        assert snap is not None

        for _ in range(_MAX_HISTORY_CREATE_RETRIES):
            logger._ensure_history_run_created(snap[0], snap[1], session_generation=snap[3])

        assert logger._history_create_fail_count == _MAX_HISTORY_CREATE_RETRIES

        # Starting a new session resets the counter
        db.create_run.side_effect = None  # Next call succeeds
        logger.start_logging()
        assert logger._history_create_fail_count == 0


class TestAppendSamplesFailureExposesError:
    """When append_samples fails, write_error is visible in status."""

    def test_append_failure_sets_write_error(self, tmp_path: Path) -> None:
        db = MagicMock()
        db.create_run.return_value = None
        db.append_samples.side_effect = OSError("write error")
        logger = _make_logger(db, tmp_path)

        logger.start_logging()
        snap = logger._session_snapshot()
        assert snap is not None
        run_id, start_utc, start_mono, generation = snap

        logger._append_records(run_id, start_utc, start_mono, session_generation=generation)

        status = logger.status()
        assert status["write_error"] is not None
        assert "write error" in status["write_error"]
        # Sample count should NOT increment on failure
        assert logger._written_sample_count == 0


class TestDroppedSamplesLogged:
    """When history run creation has permanently failed, dropped samples are logged."""

    def test_dropped_samples_logged_when_create_run_failed(self, tmp_path: Path) -> None:
        db = MagicMock()
        db.create_run.side_effect = OSError("fail")
        logger = _make_logger(db, tmp_path)

        logger.start_logging()
        snap = logger._session_snapshot()
        assert snap is not None
        run_id, start_utc, start_mono, generation = snap

        # Exhaust retries
        for _ in range(_MAX_HISTORY_CREATE_RETRIES):
            logger._ensure_history_run_created(run_id, start_utc, session_generation=generation)

        # Now append_records should log about dropped samples
        with patch("vibesensor.metrics_log.logger.LOGGER") as mock_logger:
            logger._append_records(run_id, start_utc, start_mono, session_generation=generation)
            # Verify warning about dropped samples was logged
            warning_calls = [
                call for call in mock_logger.warning.call_args_list if "Dropping" in str(call)
            ]
            assert len(warning_calls) > 0, "Expected warning about dropped samples"
        # append_samples should NOT have been called since run was never created
        db.append_samples.assert_not_called()


class TestStatusAlwaysIncludesWriteError:
    """The status dict always has a write_error key."""

    def test_write_error_none_by_default(self, tmp_path: Path) -> None:
        logger = _make_logger(None, tmp_path)
        status = logger.status()
        assert "write_error" in status
        assert status["write_error"] is None

    def test_write_error_survives_through_recording(self, tmp_path: Path) -> None:
        db = MagicMock()
        db.create_run.side_effect = OSError("boom")
        logger = _make_logger(db, tmp_path)

        logger.start_logging()
        snap = logger._session_snapshot()
        assert snap is not None
        logger._ensure_history_run_created(snap[0], snap[1], session_generation=snap[3])

        # Error persists across status calls
        assert logger.status()["write_error"] is not None
        assert logger.status()["write_error"] is not None

    def test_stop_logging_resets_write_error(self, tmp_path: Path) -> None:
        db = MagicMock()
        db.create_run.side_effect = OSError("boom")
        logger = _make_logger(db, tmp_path)

        logger.start_logging()
        snap = logger._session_snapshot()
        assert snap is not None
        logger._ensure_history_run_created(snap[0], snap[1], session_generation=snap[3])
        assert logger.status()["write_error"] is not None

        logger.stop_logging()
        assert logger.status()["write_error"] is None
