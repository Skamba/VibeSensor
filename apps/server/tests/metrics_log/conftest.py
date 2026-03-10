"""Shared fixtures for metrics_log tests.

Provides a ``make_logger`` factory fixture that eliminates the ~10 repeated
keyword arguments every MetricsLogger constructor call requires, and shared
fake collaborators used across multiple test modules.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from vibesensor.metrics_log import MetricsLogger, MetricsLoggerConfig

# ---------------------------------------------------------------------------
# Fake collaborators
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _FakeRecord:
    client_id: str
    name: str
    sample_rate_hz: int
    latest_metrics: dict
    location: str = ""
    frames_total: int = 0
    frames_dropped: int = 0
    queue_overflow_drops: int = 0


class _FakeRegistry:
    """Registry with one active and one stale client."""

    def __init__(self) -> None:
        self._records: dict[str, _FakeRecord] = {
            "active": _FakeRecord(
                client_id="active",
                name="front-left wheel",
                location="front_left_wheel",
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
                location="rear_right_wheel",
                sample_rate_hz=800,
                latest_metrics={
                    "combined": {
                        "peaks": [{"hz": 28.0, "amp": 0.26}],
                        "strength_metrics": {
                            "vibration_strength_db": 28.0,
                            "strength_bucket": "l4",
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


class _FakeGPSMonitor:
    speed_mps: float | None = None
    effective_speed_mps: float | None = None
    override_speed_mps: float | None = None

    def resolve_speed(self):
        from vibesensor.gps_speed import SpeedResolution

        if isinstance(self.override_speed_mps, (int, float)):
            return SpeedResolution(
                speed_mps=float(self.override_speed_mps),
                fallback_active=False,
                source="manual",
            )
        if isinstance(self.speed_mps, (int, float)):
            return SpeedResolution(
                speed_mps=float(self.speed_mps),
                fallback_active=False,
                source="gps",
            )
        return SpeedResolution(speed_mps=None, fallback_active=False, source="none")


class _FakeProcessor:
    def __init__(self, registry: _FakeRegistry | None = None) -> None:
        self._registry = registry

    def latest_sample_xyz(self, client_id: str):
        return (0.01, 0.02, 0.03)

    def latest_sample_rate_hz(self, client_id: str):
        return 800

    def latest_metrics(self, client_id: str) -> dict:
        if self._registry is None:
            return {}
        rec = self._registry.get(client_id)
        return rec.latest_metrics if rec is not None else {}

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


class _MutableFakeAnalysisSettings(_FakeAnalysisSettings):
    def __init__(self) -> None:
        self.values: dict[str, float] = {
            "tire_width_mm": 285.0,
            "tire_aspect_pct": 30.0,
            "rim_in": 21.0,
            "final_drive_ratio": 3.08,
            "current_gear_ratio": 0.64,
        }

    def snapshot(self) -> dict[str, float]:
        return dict(self.values)


class _FakeHistoryDB:
    def __init__(self) -> None:
        self.create_calls: list[tuple[str, str]] = []
        self.append_calls: list[tuple[str, int]] = []
        self.finalize_calls: list[str] = []
        self.updated_metadata: list[tuple[str, dict[str, Any]]] = []

    def create_run(self, run_id: str, start_time_utc: str, metadata: dict) -> None:
        self.create_calls.append((run_id, start_time_utc))

    def append_samples(self, run_id: str, samples: list[dict]) -> None:
        self.append_calls.append((run_id, len(samples)))

    def finalize_run(self, run_id: str, end_time_utc: str) -> None:
        self.finalize_calls.append(run_id)

    def update_run_metadata(self, run_id: str, metadata: dict) -> bool:
        self.updated_metadata.append((run_id, metadata))
        return True

    def finalize_run_with_metadata(self, run_id: str, end_time_utc: str, metadata: dict) -> None:
        self.updated_metadata.append((run_id, metadata))
        self.finalize_calls.append(run_id)

    def analyzing_run_health(self) -> dict:
        return {"analyzing_run_count": 0, "analyzing_oldest_age_s": None}


class _FailingCreateRunHistoryDB(_FakeHistoryDB):
    def create_run(self, run_id: str, start_time_utc: str, metadata: dict) -> None:
        raise sqlite3.OperationalError("create_run boom")


class _FailingAppendOnceHistoryDB(_FakeHistoryDB):
    """Fails append_samples enough times to exhaust the retry budget, then succeeds."""

    def __init__(self) -> None:
        super().__init__()
        # Must exceed _MAX_APPEND_RETRIES (3) to actually surface a write error
        from vibesensor.metrics_log.logger import _MAX_APPEND_RETRIES

        self._append_failures_remaining = _MAX_APPEND_RETRIES

    def append_samples(self, run_id: str, samples: list[dict]) -> None:
        if self._append_failures_remaining > 0:
            self._append_failures_remaining -= 1
            raise sqlite3.OperationalError("append boom")
        super().append_samples(run_id, samples)


# ---------------------------------------------------------------------------
# Factory fixture — eliminates ~10 repeated kwargs per call site
# ---------------------------------------------------------------------------


def _make_logger(
    tmp_path: Path,
    *,
    registry: object | None = None,
    gps_monitor: object | None = None,
    processor: object | None = None,
    analysis_settings: object | None = None,
    history_db: object | None = None,
    **extra: Any,
) -> MetricsLogger:
    """Build a ``MetricsLogger`` with sensible test defaults."""
    # Separate MetricsLoggerConfig fields from runtime-collaborator overrides.
    config_fields = {
        k: extra.pop(k)
        for k in list(extra)
        if k
        in (
            "enabled",
            "log_path",
            "metrics_log_hz",
            "sensor_model",
            "default_sample_rate_hz",
            "fft_window_size_samples",
            "fft_window_type",
            "peak_picker_method",
            "accel_scale_g_per_lsb",
            "persist_history_db",
            "no_data_timeout_s",
        )
    }
    config = MetricsLoggerConfig(
        enabled=config_fields.get("enabled", False),
        log_path=config_fields.get("log_path", tmp_path / "metrics.jsonl"),
        metrics_log_hz=config_fields.get("metrics_log_hz", 2),
        sensor_model=config_fields.get("sensor_model", "ADXL345"),
        default_sample_rate_hz=config_fields.get("default_sample_rate_hz", 800),
        fft_window_size_samples=config_fields.get("fft_window_size_samples", 1024),
        fft_window_type=config_fields.get("fft_window_type", "hann"),
        peak_picker_method=config_fields.get("peak_picker_method", "max_peak_amp_across_axes"),
        accel_scale_g_per_lsb=config_fields.get("accel_scale_g_per_lsb"),
        persist_history_db=config_fields.get("persist_history_db", True),
        no_data_timeout_s=config_fields.get("no_data_timeout_s", 15.0),
    )
    reg = registry or _FakeRegistry()
    return MetricsLogger(
        config,
        registry=reg,
        gps_monitor=gps_monitor or _FakeGPSMonitor(),
        processor=processor or _FakeProcessor(registry=reg),  # type: ignore[arg-type]
        analysis_settings=analysis_settings or _FakeAnalysisSettings(),
        history_db=history_db,
        **extra,
    )


@pytest.fixture
def make_logger(tmp_path: Path):
    """Factory fixture: call ``make_logger(...)`` to get a MetricsLogger.

    Accepts the same keyword overrides as ``MetricsLogger`` (e.g.
    ``make_logger(history_db=my_db, language_provider=lambda: "nl")``).
    Any dependency not supplied gets a sensible fake default.
    """

    def _factory(**kwargs: Any) -> MetricsLogger:
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
