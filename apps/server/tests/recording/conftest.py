"""Shared fixtures for recorder tests.

``make_logger`` builds a ``RunRecorder`` with test defaults. Speed comes from
real GPS/OBD speed-source services (``speed_rig``) and persistence from a real
sqlite ``HistoryDB`` (``history_db``); only the sensor registry/processor and
settings reader are lightweight stubs.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from test_support.obd_runtime import build_connected_obd_runtime_parts

from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.domain.car import CarSnapshot
from vibesensor.history.history_db import HistoryDB
from vibesensor.ingest.sensor_timing import SensorTimingGuard
from vibesensor.live.payload_types import ClientMetrics
from vibesensor.recording._recorder_types import RunRecorderConfig
from vibesensor.recording.recorder import RunRecorder
from vibesensor.recording.run_schema import RunMetadata
from vibesensor.recording.sensor_frame import SensorFrame
from vibesensor.speed.gps_speed import GPSSpeedMonitor
from vibesensor.speed.obd.polling import ObdPidPollResult, ObdPollResult
from vibesensor.speed.obd.service import ObdService
from vibesensor.speed.source_coordinator import (
    SpeedSourceObservationService,
    SpeedSourceServices,
    build_speed_source_services,
)

# ---------------------------------------------------------------------------
# Fake collaborators
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _FakeRecord:
    client_id: str
    name: str
    sample_rate_hz: int
    latest_metrics: ClientMetrics
    firmware_version: str = "1.0.0"
    location_code: str = ""
    frames_total: int = 0
    frames_dropped: int = 0
    expected_frames_dropped: int = 0
    queue_overflow_drops: int = 0
    server_queue_drops: int = 0
    parse_errors: int = 0
    timing_guard: SensorTimingGuard = field(default_factory=SensorTimingGuard)


class _FakeRegistry:
    """Registry with one active and one stale client."""

    def __init__(self) -> None:
        self._records: dict[str, _FakeRecord] = {
            "active": _FakeRecord(
                client_id="active",
                name="front-left wheel",
                location_code="front_left_wheel",
                sample_rate_hz=800,
                latest_metrics={
                    "combined": {
                        "peaks": [{"hz": 15.0, "amp": 0.12}],
                        "strength_metrics": {
                            "vibration_strength_db": 22.0,
                            "strength_bucket": "l2",
                            "peak_amp_g": 0.15,
                            "noise_floor_amp_g": 0.003,
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
                },
            ),
            "stale": _FakeRecord(
                client_id="stale",
                name="rear-right wheel",
                location_code="rear_right_wheel",
                sample_rate_hz=800,
                latest_metrics={
                    "combined": {
                        "peaks": [{"hz": 28.0, "amp": 0.26}],
                        "strength_metrics": {
                            "vibration_strength_db": 28.0,
                            "strength_bucket": "l4",
                            "peak_amp_g": 0.26,
                            "noise_floor_amp_g": 0.004,
                            "top_peaks": [
                                {
                                    "hz": 28.0,
                                    "amp": 0.26,
                                    "vibration_strength_db": 28.0,
                                    "strength_bucket": "l4",
                                },
                            ],
                        },
                    },
                    "x": {"rms": 0.10, "p2p": 0.22, "peaks": [{"hz": 28.0, "amp": 0.26}]},
                    "y": {"rms": 0.09, "p2p": 0.18, "peaks": [{"hz": 29.0, "amp": 0.20}]},
                    "z": {"rms": 0.08, "p2p": 0.17, "peaks": [{"hz": 27.0, "amp": 0.19}]},
                },
            ),
        }

    def active_client_ids(self) -> list[str]:
        return ["active"]

    def get(self, client_id: str) -> _FakeRecord | None:
        return self._records.get(client_id)


class _SingleSensorRegistry(_FakeRegistry):
    """One live sensor whose runtime record carries no location code."""

    def __init__(self, sensor_id: str) -> None:
        super().__init__()
        record = self._records["active"]
        record.client_id = sensor_id
        record.name = sensor_id
        record.location_code = ""
        self._sensor_id = sensor_id
        self._records = {sensor_id: record}

    def active_client_ids(self) -> list[str]:
        return [self._sensor_id]


class _NoActiveRegistry(_FakeRegistry):
    def active_client_ids(self) -> list[str]:
        return []


@dataclass(slots=True)
class SpeedRig:
    """Real GPS + OBD speed-source services, driven only through public APIs."""

    gps: GPSSpeedMonitor
    obd: ObdService
    services: SpeedSourceServices

    @property
    def observation(self) -> SpeedSourceObservationService:
        return self.services.observation

    def gps_speed(self, speed_mps: float | None) -> None:
        self.gps.speed_mps = speed_mps

    def manual(self, speed_kmh: float) -> None:
        self.services.control.apply_speed_source_settings(
            effective_speed_kmh=speed_kmh,
            manual_source_selected=True,
            selected_source="gps",
        )

    def manual_fallback(self, speed_kmh: float) -> None:
        """GPS selected but silent, so the configured manual speed takes over."""
        self.services.control.apply_speed_source_settings(
            effective_speed_kmh=speed_kmh,
            manual_source_selected=False,
            selected_source="gps",
        )
        self.gps.speed_mps = None

    def obd_reading(self, *, speed_kmh: float, rpm: float | None) -> None:
        self.services.control.apply_speed_source_settings(
            effective_speed_kmh=None,
            manual_source_selected=False,
            selected_source="obd2",
            obd_device_mac=_OBD_MAC,
            obd_device_name="OBDLink MX+",
        )
        now = time.monotonic()
        self.obd.apply_poll_cycle(
            ObdPollResult(
                rpm=_pid_result(rpm, now) if rpm is not None else ObdPidPollResult.skipped(),
                speed=_pid_result(speed_kmh, now),
            )
        )


_OBD_MAC = "02000000004d"


def _pid_result(value: float, started_at_s: float) -> ObdPidPollResult:
    return ObdPidPollResult(
        value=value,
        raw_response=None,
        error=None,
        duration_s=0.01,
        executed=True,
        started_at_s=started_at_s,
    )


def build_speed_rig() -> SpeedRig:
    gps = GPSSpeedMonitor(gps_enabled=True)
    obd = build_connected_obd_runtime_parts(clock=time.monotonic).obd
    return SpeedRig(
        gps=gps,
        obd=obd,
        services=build_speed_source_services(gps_monitor=gps, obd=obd),
    )


class _FakeProcessor:
    def __init__(self, registry: _FakeRegistry | None = None) -> None:
        self._registry = registry
        self.flush_calls: list[tuple[str, str]] = []

    def flush_client_buffer(
        self,
        client_id: str,
        *,
        reason: str = "sensor reset",
    ) -> None:
        self.flush_calls.append((client_id, reason))

    def latest_sample_xyz(self, client_id: str):
        return (0.01, 0.02, 0.03)

    def latest_sample_rate_hz(self, client_id: str):
        return 800

    def latest_analysis_time_range(self, client_id: str):
        return None

    def compute_metrics(self, client_id: str, sample_rate_hz: int | None = None) -> ClientMetrics:
        return self.latest_metrics(client_id)

    def latest_metrics(self, client_id: str) -> ClientMetrics:
        if self._registry is None:
            return {}
        rec = self._registry.get(client_id)
        return rec.latest_metrics if rec is not None else {}

    def clients_with_recent_data(self, client_ids: list[str], max_age_s: float = 3.0) -> list[str]:
        return list(client_ids)


class _FakeAnalysisSettings:
    active_car: CarSnapshot | None = None

    def analysis_settings_snapshot(self) -> AnalysisSettingsSnapshot:
        return AnalysisSettingsSnapshot(
            tire_width_mm=285.0,
            tire_aspect_pct=30.0,
            rim_in=21.0,
            final_drive_ratio=3.08,
            current_gear_ratio=0.64,
        )

    def active_car_snapshot(self) -> CarSnapshot | None:
        return self.active_car


class _MutableFakeAnalysisSettings(_FakeAnalysisSettings):
    def __init__(self) -> None:
        self.values: dict[str, float] = {
            "tire_width_mm": 285.0,
            "tire_aspect_pct": 30.0,
            "rim_in": 21.0,
            "final_drive_ratio": 3.08,
            "current_gear_ratio": 0.64,
        }
        self.active_car: CarSnapshot | None = None

    def analysis_settings_snapshot(self) -> AnalysisSettingsSnapshot:
        return AnalysisSettingsSnapshot(**self.values)


class _FailingCreateRunHistoryDB(HistoryDB):
    def create_run(self, run_id: str, start_time_utc: str, metadata: RunMetadata) -> None:
        raise sqlite3.OperationalError("create_run boom")


class _FailingAppendHistoryDB(HistoryDB):
    """Fails append_samples enough times to exhaust the retry budget, then succeeds."""

    def __init__(self, db_path: Path) -> None:
        super().__init__(db_path)
        from vibesensor.recording.recorder import _MAX_APPEND_RETRIES

        self.append_failures_remaining = _MAX_APPEND_RETRIES

    def append_samples(self, run_id: str, samples: list[SensorFrame]) -> int:
        if self.append_failures_remaining > 0:
            self.append_failures_remaining -= 1
            raise sqlite3.OperationalError("append boom")
        return super().append_samples(run_id, samples)


# ---------------------------------------------------------------------------
# Factory fixture — eliminates ~10 repeated kwargs per call site
# ---------------------------------------------------------------------------


def _make_logger(
    tmp_path: Path,
    *,
    registry: object | None = None,
    gps_monitor: object | None = None,
    processor: object | None = None,
    settings_reader: object | None = None,
    history_db: object | None = None,
    **extra: Any,
) -> RunRecorder:
    """Build a ``RunRecorder`` with sensible test defaults."""
    # Separate RunRecorderConfig fields from runtime-collaborator overrides.
    config_fields = {
        k: extra.pop(k)
        for k in list(extra)
        if k
        in (
            "metrics_log_hz",
            "sensor_model",
            "default_sample_rate_hz",
            "fft_window_size_samples",
            "accel_scale_g_per_lsb",
            "persist_history_db",
            "no_data_timeout_s",
        )
    }
    config = RunRecorderConfig(
        metrics_log_hz=config_fields.get("metrics_log_hz", 2),
        sensor_model=config_fields.get("sensor_model", "ADXL345"),
        default_sample_rate_hz=config_fields.get("default_sample_rate_hz", 800),
        fft_window_size_samples=config_fields.get("fft_window_size_samples", 1024),
        accel_scale_g_per_lsb=config_fields.get("accel_scale_g_per_lsb"),
        persist_history_db=config_fields.get("persist_history_db", True),
        no_data_timeout_s=config_fields.get("no_data_timeout_s", 15.0),
    )
    reg = registry or _FakeRegistry()
    return RunRecorder(
        config,
        registry=reg,
        gps_monitor=gps_monitor or build_speed_rig().observation,
        processor=processor or _FakeProcessor(registry=reg),
        settings_reader=settings_reader or _FakeAnalysisSettings(),
        history_db=history_db,
        **extra,
    )


@pytest.fixture
def make_logger(tmp_path: Path):
    """Factory fixture: call ``make_logger(...)`` to get a RunRecorder.

    Accepts the same keyword overrides as ``RunRecorder`` (e.g.
    ``make_logger(history_db=my_db, ui_preferences=my_ui_preferences)``).
    Any dependency not supplied gets a sensible fake default.
    """

    def _factory(**kwargs: Any) -> RunRecorder:
        return _make_logger(tmp_path, **kwargs)

    return _factory


# ---------------------------------------------------------------------------
# Expose fake classes for direct use in tests via fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_registry():
    """Return a fresh ``_FakeRegistry`` instance."""
    return _FakeRegistry()


@pytest.fixture
def speed_rig() -> SpeedRig:
    """Return real speed-source services with no speed yet."""
    return build_speed_rig()


@pytest.fixture
def history_db(tmp_path: Path):
    """Return a real sqlite ``HistoryDB`` in ``tmp_path``."""
    db = HistoryDB(tmp_path / "history.db")
    yield db
    db.close()


@pytest.fixture
def mutable_fake_settings():
    """Return a ``_MutableFakeAnalysisSettings`` instance."""
    return _MutableFakeAnalysisSettings()


@pytest.fixture
def failing_create_run_db(tmp_path: Path):
    db = _FailingCreateRunHistoryDB(tmp_path / "failing-create.db")
    yield db
    db.close()


@pytest.fixture
def failing_append_once_db(tmp_path: Path):
    db = _FailingAppendHistoryDB(tmp_path / "failing-append.db")
    yield db
    db.close()


@pytest.fixture
def single_sensor_registry():
    """Factory for a one-sensor registry without a runtime location."""
    return _SingleSensorRegistry


@pytest.fixture
def no_active_registry():
    """Return a ``_NoActiveRegistry`` instance."""
    return _NoActiveRegistry()
