from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from vibesensor.metrics_log import MetricsLogger

# -- MetricsLogger._safe_metric ------------------------------------------------


def test_safe_metric_valid() -> None:
    metrics = {"x": {"rms": 0.05, "p2p": 0.12}}
    result = MetricsLogger._safe_metric(metrics, "x", "rms")
    assert result == 0.05


def test_safe_metric_missing_axis() -> None:
    metrics = {"x": {"rms": 0.05}}
    assert MetricsLogger._safe_metric(metrics, "y", "rms") is None


def test_safe_metric_missing_key() -> None:
    metrics = {"x": {"rms": 0.05}}
    assert MetricsLogger._safe_metric(metrics, "x", "p2p") is None


def test_safe_metric_nan_returns_none() -> None:
    metrics = {"x": {"rms": float("nan")}}
    assert MetricsLogger._safe_metric(metrics, "x", "rms") is None


def test_safe_metric_inf_returns_none() -> None:
    metrics = {"x": {"rms": float("inf")}}
    assert MetricsLogger._safe_metric(metrics, "x", "rms") is None


def test_safe_metric_axis_not_dict_returns_none() -> None:
    metrics = {"x": "not_a_dict"}
    assert MetricsLogger._safe_metric(metrics, "x", "rms") is None


def test_safe_metric_non_numeric_returns_none() -> None:
    metrics = {"x": {"rms": "abc"}}
    assert MetricsLogger._safe_metric(metrics, "x", "rms") is None


@dataclass(slots=True)
class _FakeRecord:
    client_id: str
    name: str
    sample_rate_hz: int
    latest_metrics: dict
    frames_dropped: int = 0
    queue_overflow_drops: int = 0


class _FakeRegistry:
    def __init__(self) -> None:
        self._records = {
            "active": _FakeRecord(
                client_id="active",
                name="front-left wheel",
                sample_rate_hz=800,
                latest_metrics={
                    "combined": {
                        "vib_mag_rms": 0.09,
                        "vib_mag_p2p": 0.20,
                        "noise_floor_amp_p20_g": 0.01,
                        "peaks": [{"hz": 15.0, "amp": 0.12}],
                    },
                    "x": {"rms": 0.04, "p2p": 0.11, "peaks": [{"hz": 15.0, "amp": 0.12}]},
                    "y": {"rms": 0.03, "p2p": 0.10, "peaks": [{"hz": 16.0, "amp": 0.08}]},
                    "z": {"rms": 0.02, "p2p": 0.09, "peaks": [{"hz": 14.0, "amp": 0.07}]},
                },
            ),
            "stale": _FakeRecord(
                client_id="stale",
                name="rear-right wheel",
                sample_rate_hz=800,
                latest_metrics={
                    "combined": {
                        "vib_mag_rms": 0.22,
                        "vib_mag_p2p": 0.40,
                        "noise_floor_amp_p20_g": 0.02,
                        "peaks": [{"hz": 28.0, "amp": 0.26}],
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


class _FakeGPSMonitor:
    speed_mps = None
    effective_speed_mps = None
    override_speed_mps = None


class _FakeProcessor:
    def latest_sample_xyz(self, client_id: str):
        return (0.01, 0.02, 0.03)

    def latest_sample_rate_hz(self, client_id: str):
        return 800


class _FakeAnalysisSettings:
    def snapshot(self) -> dict[str, float]:
        return {
            "tire_width_mm": 285.0,
            "tire_aspect_pct": 30.0,
            "rim_in": 21.0,
            "final_drive_ratio": 3.08,
            "current_gear_ratio": 0.64,
        }


def test_build_sample_records_uses_only_active_clients(tmp_path: Path) -> None:
    logger = MetricsLogger(
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
    )

    rows = logger._build_sample_records(
        run_id="run-1",
        t_s=1.0,
        timestamp_utc="2026-02-16T12:00:00+00:00",
    )

    assert len(rows) == 1
    assert rows[0]["client_id"] == "active"
    assert rows[0]["client_name"] == "front-left wheel"


@pytest.mark.parametrize("missing_key", ["vib_mag_rms", "vib_mag_p2p"])
def test_build_sample_records_requires_combined_vibration_magnitudes(
    tmp_path: Path, missing_key: str
) -> None:
    registry = _FakeRegistry()
    del registry._records["active"].latest_metrics["combined"][missing_key]
    logger = MetricsLogger(
        enabled=False,
        log_path=tmp_path / "metrics.jsonl",
        metrics_log_hz=2,
        registry=registry,
        gps_monitor=_FakeGPSMonitor(),
        processor=_FakeProcessor(),
        analysis_settings=_FakeAnalysisSettings(),
        sensor_model="ADXL345",
        default_sample_rate_hz=800,
        fft_window_size_samples=1024,
    )

    with pytest.raises(ValueError, match=missing_key):
        logger._build_sample_records(
            run_id="run-1",
            t_s=1.0,
            timestamp_utc="2026-02-16T12:00:00+00:00",
        )


def test_speed_source_reports_override_when_override_set(tmp_path: Path) -> None:
    """speed_source should be 'override' when override_speed_mps is set."""
    gps = _FakeGPSMonitor()
    gps.speed_mps = 10.0  # GPS available
    gps.override_speed_mps = 20.0  # Override active
    gps.effective_speed_mps = 20.0  # Override takes priority

    logger = MetricsLogger(
        enabled=False,
        log_path=tmp_path / "metrics.jsonl",
        metrics_log_hz=2,
        registry=_FakeRegistry(),
        gps_monitor=gps,
        processor=_FakeProcessor(),
        analysis_settings=_FakeAnalysisSettings(),
        sensor_model="ADXL345",
        default_sample_rate_hz=800,
        fft_window_size_samples=1024,
    )

    rows = logger._build_sample_records(
        run_id="run-1",
        t_s=1.0,
        timestamp_utc="2026-02-16T12:00:00+00:00",
    )

    assert len(rows) == 1
    assert rows[0]["speed_source"] == "override"
    assert rows[0]["speed_kmh"] == pytest.approx(20.0 * 3.6, abs=0.01)


def test_speed_source_reports_gps_when_no_override(tmp_path: Path) -> None:
    """speed_source should be 'gps' when GPS is available and no override."""
    gps = _FakeGPSMonitor()
    gps.speed_mps = 10.0
    gps.override_speed_mps = None
    gps.effective_speed_mps = 10.0

    logger = MetricsLogger(
        enabled=False,
        log_path=tmp_path / "metrics.jsonl",
        metrics_log_hz=2,
        registry=_FakeRegistry(),
        gps_monitor=gps,
        processor=_FakeProcessor(),
        analysis_settings=_FakeAnalysisSettings(),
        sensor_model="ADXL345",
        default_sample_rate_hz=800,
        fft_window_size_samples=1024,
    )

    rows = logger._build_sample_records(
        run_id="run-1",
        t_s=1.0,
        timestamp_utc="2026-02-16T12:00:00+00:00",
    )

    assert len(rows) == 1
    assert rows[0]["speed_source"] == "gps"
    assert rows[0]["speed_kmh"] == pytest.approx(10.0 * 3.6, abs=0.01)


def test_speed_source_reports_missing_when_nothing_set(tmp_path: Path) -> None:
    """speed_source should be 'missing' when neither GPS nor override is set."""
    logger = MetricsLogger(
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
    )

    rows = logger._build_sample_records(
        run_id="run-1",
        t_s=1.0,
        timestamp_utc="2026-02-16T12:00:00+00:00",
    )

    assert len(rows) == 1
    assert rows[0]["speed_source"] == "missing"
    assert rows[0]["speed_kmh"] is None
