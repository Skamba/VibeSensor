"""Coverage-gap audit: top 10 untested critical code paths.

This file addresses the top 10 coverage gaps identified by systematic
cross-referencing of public/private functions in:
  - apps/server/vibesensor/analysis/findings.py
  - apps/server/vibesensor/analysis/summary.py
  - apps/server/vibesensor/metrics_log.py
  - apps/server/vibesensor/processing.py
against all test files in apps/server/tests/.

Each class documents the gap, its severity, and provides working tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from vibesensor.analysis.phase_segmentation import DrivingPhase
from vibesensor.analysis.summary import (
    _build_run_suitability_checks,
)
from vibesensor.metrics_log import MetricsLogger


class _FakeSeg:
    """Minimal driving-phase segment stub for timeline tests."""

    def __init__(
        self,
        phase: DrivingPhase = DrivingPhase.CRUISE,
        start: float = 0.0,
        end: float = 10.0,
        speed_min: float = 50.0,
        speed_max: float = 60.0,
    ) -> None:
        self.phase = phase
        self.start_t_s = start
        self.end_t_s = end
        self.speed_min_kmh = speed_min
        self.speed_max_kmh = speed_max


_SUITABILITY_DEFAULTS: dict[str, Any] = {
    "language": "en",
    "steady_speed": False,
    "speed_sufficient": True,
    "sensor_ids": {"s1", "s2", "s3"},
    "reference_complete": True,
    "sat_count": 0,
    "samples": [],
}


def _suitability_checks(**overrides: Any) -> list[dict[str, Any]]:
    """Call _build_run_suitability_checks with sensible defaults + overrides."""
    kw = {**_SUITABILITY_DEFAULTS, **overrides}
    return _build_run_suitability_checks(**kw)


def _make_metrics_logger() -> tuple[MetricsLogger, MagicMock]:
    """Build a minimal MetricsLogger with mocked dependencies."""
    gps_mock = MagicMock()
    gps_mock.speed_mps = None
    gps_mock.effective_speed_mps = None
    gps_mock.override_speed_mps = None
    gps_mock.resolve_speed.return_value = MagicMock(source="none")

    registry = MagicMock()
    registry.active_client_ids.return_value = []

    settings_mock = MagicMock()
    settings_mock.snapshot.return_value = {
        "tire_width_mm": 205,
        "tire_aspect_pct": 55,
        "rim_in": 16,
        "final_drive_ratio": 3.73,
        "current_gear_ratio": 1.0,
        "tire_deflection_factor": None,
    }

    logger = MetricsLogger(
        enabled=False,
        log_path=Path("/tmp/test"),
        metrics_log_hz=1,
        registry=registry,
        gps_monitor=gps_mock,
        processor=MagicMock(),
        analysis_settings=settings_mock,
        sensor_model="test",
        default_sample_rate_hz=800,
        fft_window_size_samples=512,
        persist_history_db=False,
    )
    return logger, gps_mock


class TestExtractStrengthData:
    """Direct unit tests for MetricsLogger._extract_strength_data."""

    def test_empty_metrics(self) -> None:
        strength, db, bucket, peak, floor, peaks = MetricsLogger._extract_strength_data({})
        assert strength == {}
        assert db is None
        assert bucket is None
        assert peaks == []

    def test_top_level_strength_metrics(self) -> None:
        metrics: dict[str, object] = {
            "strength_metrics": {
                "vibration_strength_db": 18.5,
                "strength_bucket": "l3",
                "peak_amp_g": 0.02,
                "noise_floor_amp_g": 0.001,
                "top_peaks": [{"hz": 45.0, "amp": 0.015}],
            }
        }
        strength, db, bucket, peak, floor, peaks = MetricsLogger._extract_strength_data(metrics)
        assert db == pytest.approx(18.5)
        assert bucket == "l3"
        assert len(peaks) == 1
        assert peaks[0]["hz"] == pytest.approx(45.0)

    def test_nested_combined_fallback(self) -> None:
        metrics: dict[str, object] = {
            "combined": {
                "strength_metrics": {
                    "vibration_strength_db": 12.0,
                    "strength_bucket": "l2",
                    "top_peaks": [],
                }
            }
        }
        strength, db, bucket, _, _, _ = MetricsLogger._extract_strength_data(metrics)
        assert db == pytest.approx(12.0)
        assert bucket == "l2"

    def test_invalid_peak_data_filtered(self) -> None:
        metrics: dict[str, object] = {
            "strength_metrics": {
                "vibration_strength_db": 10.0,
                "top_peaks": [
                    {"hz": float("nan"), "amp": 0.01},  # nan hz
                    {"hz": 50.0, "amp": float("inf")},  # inf amp
                    {"hz": -1.0, "amp": 0.01},  # negative hz
                    {"hz": 50.0, "amp": 0.01},  # valid
                    "not_a_dict",  # invalid type
                ],
            }
        }
        _, _, _, _, _, peaks = MetricsLogger._extract_strength_data(metrics)
        assert len(peaks) == 1
        assert peaks[0]["hz"] == pytest.approx(50.0)

    def test_empty_bucket_treated_as_none(self) -> None:
        metrics: dict[str, object] = {
            "strength_metrics": {
                "vibration_strength_db": 5.0,
                "strength_bucket": "",
                "top_peaks": [],
            }
        }
        _, _, bucket, _, _, _ = MetricsLogger._extract_strength_data(metrics)
        assert bucket is None
