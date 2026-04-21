"""Shared fixtures for metrics_log tests.

Provides a ``make_logger`` factory fixture that eliminates the ~10 repeated
keyword arguments every RunRecorder constructor call requires, and shared
fake collaborators used across multiple test modules.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from vibesensor.domain import CarSnapshot
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.shared.types.history_records import AnalyzingRunHealth
from vibesensor.shared.types.payload_types import ClientMetrics
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame
from vibesensor.use_cases.run import RunRecorder, RunRecorderConfig

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
    queue_overflow_drops: int = 0
    server_queue_drops: int = 0
    parse_errors: int = 0


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


class _NoActiveRegistry(_FakeRegistry):
    def active_client_ids(self) -> list[str]:
        return []


_RAW_GPS_SPEED_UNSET = object()


class _FakeGPSMonitor:
    speed_mps: float | None = None
    effective_speed_mps: float | None = None
    override_speed_mps: float | None = None
    raw_gps_speed_mps: object | float | None = _RAW_GPS_SPEED_UNSET
    resolved_source: str | None = None
    fallback_active: bool = False
    engine_rpm: float | None = None
    engine_rpm_source: str | None = None
    speed_status_override: Any = None
    obd_status_override: Any = None

    @property
    def gps_speed_mps(self) -> float | None:
        if self.raw_gps_speed_mps is _RAW_GPS_SPEED_UNSET:
            return self.speed_mps
        return self.raw_gps_speed_mps if isinstance(self.raw_gps_speed_mps, (int, float)) else None

    def resolve_speed(self):
        from vibesensor.adapters.gps.gps_speed import SpeedResolution

        if isinstance(self.override_speed_mps, (int, float)):
            return SpeedResolution(
                speed_mps=float(self.override_speed_mps),
                fallback_active=self.fallback_active,
                source="manual",
            )
        if isinstance(self.speed_mps, (int, float)):
            return SpeedResolution(
                speed_mps=float(self.speed_mps),
                fallback_active=self.fallback_active,
                source=str(self.resolved_source or "gps"),
            )
        return SpeedResolution(speed_mps=None, fallback_active=self.fallback_active, source="none")

    def status_snapshot(self):
        from vibesensor.adapters.gps.speed_status import SpeedSourceStatusSnapshot

        if self.speed_status_override is not None:
            return self.speed_status_override

        speed_mps = self.effective_speed_mps
        if speed_mps is None and isinstance(self.speed_mps, (int, float)):
            speed_mps = float(self.speed_mps)
        effective_speed_kmh = round(float(speed_mps) * 3.6, 2) if speed_mps is not None else None
        return SpeedSourceStatusSnapshot(
            gps_enabled=True,
            connection_state="connected",
            device="gps0",
            fix_mode=3,
            fix_dimension="3d",
            speed_confidence="high",
            epx_m=0.6,
            epy_m=0.6,
            epv_m=1.2,
            last_update_age_s=0.2 if effective_speed_kmh is not None else None,
            raw_speed_kmh=effective_speed_kmh,
            effective_speed_kmh=effective_speed_kmh,
            last_error=None,
            reconnect_delay_s=None,
            fallback_active=self.fallback_active,
            speed_source=str(self.resolved_source or "gps"),
            stale_timeout_s=8.0,
        )

    def obd_status(self):
        from vibesensor.adapters.obd.models import ObdStatusSnapshot

        if self.obd_status_override is not None:
            return self.obd_status_override

        return ObdStatusSnapshot(
            configured_device_mac="AA:BB:CC:DD:EE:FF",
            configured_device_name="Test OBD",
            connection_state="connected",
            device_mac="AA:BB:CC:DD:EE:FF",
            device_name="Test OBD",
            paired=True,
            trusted=True,
            connected=True,
            rfcomm_channel=1,
            last_sample_age_s=0.2,
            last_speed_kmh=round(float(self.speed_mps) * 3.6, 2)
            if isinstance(self.speed_mps, (int, float))
            else None,
            last_rpm=float(self.engine_rpm) if isinstance(self.engine_rpm, (int, float)) else None,
            rpm_sample_age_s=0.2 if isinstance(self.engine_rpm, (int, float)) else None,
            rpm_target_interval_ms=250,
            rpm_effective_hz=4.0 if isinstance(self.engine_rpm, (int, float)) else None,
            request_rtt_ms=85.0,
            timeout_count=0,
            error_count=0,
            poll_mode="rpm_priority",
            backoff_active=False,
            last_error=None,
            last_raw_response=None,
            reconnect_delay_s=None,
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


class _FakeHistoryDB:
    def __init__(self) -> None:
        self.create_calls: list[tuple[str, str]] = []
        self.append_calls: list[tuple[str, int]] = []
        self.finalize_calls: list[str] = []
        self.updated_metadata: list[tuple[str, RunMetadata]] = []

    async def acreate_run(self, run_id: str, start_time_utc: str, metadata: RunMetadata) -> None:
        self.create_calls.append((run_id, start_time_utc))

    async def aappend_samples(self, run_id: str, samples: list[SensorFrame]) -> int:
        self.append_calls.append((run_id, len(samples)))
        return len(samples)

    async def afinalize_run(
        self,
        run_id: str,
        end_time_utc: str,
        metadata: RunMetadata | None = None,
    ) -> None:
        if metadata is not None:
            self.updated_metadata.append((run_id, metadata))
        self.finalize_calls.append(run_id)

    async def aupdate_run_metadata(self, run_id: str, metadata: RunMetadata) -> bool:
        self.updated_metadata.append((run_id, metadata))
        return True

    async def aanalyzing_run_health(self) -> AnalyzingRunHealth:
        return AnalyzingRunHealth(analyzing_run_count=0, analyzing_oldest_age_s=None)


class _FailingCreateRunHistoryDB(_FakeHistoryDB):
    async def acreate_run(self, run_id: str, start_time_utc: str, metadata: RunMetadata) -> None:
        raise sqlite3.OperationalError("create_run boom")


class _FailingAppendOnceHistoryDB(_FakeHistoryDB):
    """Fails append_samples enough times to exhaust the retry budget, then succeeds."""

    def __init__(self) -> None:
        super().__init__()
        # Must exceed _MAX_APPEND_RETRIES (3) to actually surface a write error
        from vibesensor.use_cases.run.logger import _MAX_APPEND_RETRIES

        self._append_failures_remaining = _MAX_APPEND_RETRIES

    async def aappend_samples(self, run_id: str, samples: list[SensorFrame]) -> int:
        if self._append_failures_remaining > 0:
            self._append_failures_remaining -= 1
            raise sqlite3.OperationalError("append boom")
        return await super().aappend_samples(run_id, samples)


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
        gps_monitor=gps_monitor or _FakeGPSMonitor(),
        processor=processor or _FakeProcessor(registry=reg),
        settings_reader=settings_reader or _FakeAnalysisSettings(),
        history_db=history_db,
        **extra,
    )


@pytest.fixture
def make_logger(tmp_path: Path):
    """Factory fixture: call ``make_logger(...)`` to get a RunRecorder.

    Accepts the same keyword overrides as ``RunRecorder`` (e.g.
    ``make_logger(history_db=my_db, language_reader=my_language_reader)``).
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
def fake_gps_monitor():
    """Return a fresh ``_FakeGPSMonitor`` instance."""
    return _FakeGPSMonitor()


@pytest.fixture
def fake_history_db():
    """Return a fresh ``_FakeHistoryDB`` instance."""
    return _FakeHistoryDB()


@pytest.fixture
def mutable_fake_settings():
    """Return a ``_MutableFakeAnalysisSettings`` instance."""
    return _MutableFakeAnalysisSettings()


@pytest.fixture
def failing_create_run_db():
    """Return a ``_FailingCreateRunHistoryDB`` instance."""
    return _FailingCreateRunHistoryDB()


@pytest.fixture
def failing_append_once_db():
    """Return a ``_FailingAppendOnceHistoryDB`` instance."""
    return _FailingAppendOnceHistoryDB()


@pytest.fixture
def no_active_registry():
    """Return a ``_NoActiveRegistry`` instance."""
    return _NoActiveRegistry()
