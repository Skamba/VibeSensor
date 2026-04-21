"""Tests for history DB write-failure handling in RunRecorder (issue #296).

Verifies that DB write failures are:
1. Exposed via status().write_error
2. Logged at the correct severity
3. Tracked with a consecutive failure counter
4. Samples are logged as dropped when history run creation persistently fails
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

from vibesensor.adapters.gps.gps_speed import SpeedResolution
from vibesensor.shared.types.payload_types import ClientMetrics
from vibesensor.use_cases.run import RunRecorder, RunRecorderConfig
from vibesensor.use_cases.run.logger import _MAX_HISTORY_CREATE_RETRIES

# -- Minimal fakes -----------------------------------------------------------


@dataclass(slots=True)
class _FakeRecord:
    client_id: str
    name: str
    location_code: str
    sample_rate_hz: int
    latest_metrics: ClientMetrics
    firmware_version: str | None = None
    frames_total: int = 0
    frames_dropped: int = 0
    queue_overflow_drops: int = 0


_FAKE_LATEST_METRICS: ClientMetrics = {
    "combined": {
        "peaks": [{"hz": 15.0, "amp": 0.12}],
        "strength_metrics": {
            "vibration_strength_db": 22.0,
            "peak_amp_g": 0.12,
            "noise_floor_amp_g": 0.001,
            "strength_bucket": "l2",
            "top_peaks": [
                {
                    "hz": 15.0,
                    "amp": 0.12,
                    "vibration_strength_db": 22.0,
                    "strength_bucket": "l2",
                },
            ],
        },
    },
    "x": {"rms": 0.04, "p2p": 0.11, "peaks": [{"hz": 15.0, "amp": 0.12}]},
    "y": {"rms": 0.03, "p2p": 0.10, "peaks": [{"hz": 16.0, "amp": 0.08}]},
    "z": {"rms": 0.02, "p2p": 0.09, "peaks": [{"hz": 14.0, "amp": 0.07}]},
}


class _FakeRegistry:
    def __init__(self) -> None:
        self._records = {
            "active": _FakeRecord(
                client_id="active",
                name="front-left",
                location_code="front_left_wheel",
                sample_rate_hz=800,
                latest_metrics=_FAKE_LATEST_METRICS,
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
    engine_rpm = None
    engine_rpm_source = None

    @property
    def gps_speed_mps(self) -> float | None:
        return self.speed_mps

    def resolve_speed(self) -> SpeedResolution:
        return SpeedResolution(speed_mps=None, fallback_active=False, source="none")


class _FakeProcessor:
    def __init__(self, registry: _FakeRegistry | None = None) -> None:
        self._registry = registry

    def flush_client_buffer(
        self,
        client_id: str,
        *,
        reason: str = "sensor reset",
    ) -> None:
        return None

    def latest_sample_xyz(self, client_id: str) -> tuple[float, float, float]:
        return (0.01, 0.02, 0.03)

    def latest_sample_rate_hz(self, client_id: str) -> int:
        return 800

    def compute_metrics(self, client_id: str, sample_rate_hz: int | None = None) -> ClientMetrics:
        return self.latest_metrics(client_id)

    def latest_metrics(self, client_id: str) -> ClientMetrics:
        if self._registry is None:
            return {}
        rec = self._registry.get(client_id)
        return rec.latest_metrics if rec is not None else {}

    def clients_with_recent_data(self, client_ids: list[str], max_age_s: float = 3.0) -> list[str]:
        return list(client_ids)


def _make_logger(history_db, _tmp_path: Path) -> RunRecorder:
    reg = _FakeRegistry()
    return RunRecorder(
        RunRecorderConfig(
            metrics_log_hz=2,
            sensor_model="ADXL345",
            default_sample_rate_hz=800,
            fft_window_size_samples=1024,
        ),
        registry=reg,
        gps_monitor=_FakeGPSMonitor(),
        processor=_FakeProcessor(registry=reg),
        history_db=history_db,
    )


def _start_and_snapshot(logger: RunRecorder) -> tuple[str, str, float]:
    """Start logging and return (run_id, start_utc, start_mono)."""
    logger.start_recording()
    snap = logger._session_snapshot()
    assert snap is not None
    return snap.run_id, snap.start_time_utc, snap.start_mono_s


# -- Tests -------------------------------------------------------------------


class TestCreateRunFailureExposesWriteError:
    """When _ensure_history_run_created fails, write_error is visible in status."""

    def test_single_create_run_failure_sets_write_error(self, tmp_path: Path) -> None:
        db = MagicMock()
        db.acreate_run.side_effect = OSError("disk full")
        logger = _make_logger(db, tmp_path)

        run_id, start_utc, start_mono = _start_and_snapshot(logger)

        logger._persistence.ensure_history_run(
            run_id,
            start_utc,
        )

        status = logger.status()
        assert status.write_error is not None
        assert "disk full" in status.write_error
        assert not logger._persistence.history_run_created

    def test_create_run_success_clears_write_error(self, tmp_path: Path) -> None:
        db = MagicMock()
        db.acreate_run.side_effect = [OSError("first fail"), None]
        logger = _make_logger(db, tmp_path)

        run_id, start_utc, start_mono = _start_and_snapshot(logger)

        # First call fails
        logger._persistence.ensure_history_run(
            run_id,
            start_utc,
        )
        assert logger.status().write_error is not None

        # Second call succeeds
        logger._persistence.ensure_history_run(
            run_id,
            start_utc,
        )
        assert logger._persistence.history_run_created
        assert logger.status().write_error is None


class TestPersistentCreateRunFailureStopsRetrying:
    """After _MAX_HISTORY_CREATE_RETRIES failures, stop retrying."""

    def test_gives_up_after_max_retries(self, tmp_path: Path) -> None:
        db = MagicMock()
        db.acreate_run.side_effect = OSError("persistent failure")
        logger = _make_logger(db, tmp_path)

        run_id, start_utc, start_mono = _start_and_snapshot(logger)

        for _ in range(_MAX_HISTORY_CREATE_RETRIES + 3):
            logger._persistence.ensure_history_run(
                run_id,
                start_utc,
            )

        # Should have been called exactly _MAX_HISTORY_CREATE_RETRIES times
        assert db.acreate_run.call_count == _MAX_HISTORY_CREATE_RETRIES
        assert logger._persistence.history_create_fail_count == _MAX_HISTORY_CREATE_RETRIES
        assert not logger._persistence.history_run_created
        assert logger.status().write_error is not None
        assert "create_run failed" in str(logger.status().write_error)

    def test_retry_counter_resets_on_new_session(self, tmp_path: Path) -> None:
        db = MagicMock()
        db.acreate_run.side_effect = OSError("fail")
        logger = _make_logger(db, tmp_path)

        run_id, start_utc, _ = _start_and_snapshot(logger)

        for _ in range(_MAX_HISTORY_CREATE_RETRIES):
            logger._persistence.ensure_history_run(
                run_id,
                start_utc,
            )

        assert logger._persistence.history_create_fail_count == _MAX_HISTORY_CREATE_RETRIES

        # Starting a new session resets the counter
        db.acreate_run.side_effect = None  # Next call succeeds
        logger.start_recording()
        assert logger._persistence.history_create_fail_count == 0


class TestAppendSamplesFailureExposesError:
    """When append_samples fails, write_error is visible in status."""

    def test_append_failure_sets_write_error(self, tmp_path: Path) -> None:
        db = MagicMock()
        db.acreate_run.return_value = None
        db.aappend_samples.side_effect = OSError("write error")
        logger = _make_logger(db, tmp_path)

        run_id, start_utc, start_mono = _start_and_snapshot(logger)

        logger._sample_flush.append_records(run_id, start_utc, start_mono)

        status = logger.status()
        assert status.write_error is not None
        assert "write error" in str(status.write_error)
        # Sample count should NOT increment on failure
        assert logger._persistence.written_sample_count == 0


class TestDroppedSamplesLogged:
    """When history run creation has permanently failed, dropped samples are logged."""

    def test_dropped_samples_logged_when_create_run_failed(self, tmp_path: Path) -> None:
        db = MagicMock()
        db.acreate_run.side_effect = OSError("fail")
        logger = _make_logger(db, tmp_path)

        run_id, start_utc, start_mono = _start_and_snapshot(logger)

        # Exhaust retries
        for _ in range(_MAX_HISTORY_CREATE_RETRIES):
            logger._persistence.ensure_history_run(
                run_id,
                start_utc,
            )

        # Now append_records should log about dropped samples
        with patch("vibesensor.use_cases.run.logger.LOGGER") as mock_logger:
            logger._sample_flush.append_records(run_id, start_utc, start_mono)
            # Verify warning about dropped samples was logged
            warning_calls = [
                call for call in mock_logger.warning.call_args_list if "Dropping" in str(call)
            ]
            assert len(warning_calls) > 0, "Expected warning about dropped samples"
        # append_samples should NOT have been called since run was never created
        db.aappend_samples.assert_not_called()


class TestStatusAlwaysIncludesWriteError:
    """The status snapshot always exposes write_error."""

    def test_write_error_none_by_default(self, tmp_path: Path) -> None:
        logger = _make_logger(None, tmp_path)
        status = logger.status()
        assert status.write_error is None

    def test_write_error_survives_through_recording(self, tmp_path: Path) -> None:
        db = MagicMock()
        db.acreate_run.side_effect = OSError("boom")
        logger = _make_logger(db, tmp_path)

        run_id, start_utc, _ = _start_and_snapshot(logger)
        logger._persistence.ensure_history_run(
            run_id,
            start_utc,
        )

        # Error persists across status calls
        assert logger.status().write_error is not None
        assert len(str(logger.status().write_error)) > 0

    def test_stop_recording_resets_write_error(self, tmp_path: Path) -> None:
        db = MagicMock()
        db.acreate_run.side_effect = OSError("boom")
        logger = _make_logger(db, tmp_path)

        run_id, start_utc, _ = _start_and_snapshot(logger)
        logger._persistence.ensure_history_run(
            run_id,
            start_utc,
        )
        assert logger.status().write_error is not None

        logger.stop_recording()
        assert logger.status().write_error is None
