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


class TestBuildRunSuitabilityChecks:
    """Direct unit tests for _build_run_suitability_checks."""

    def test_all_pass(self) -> None:
        checks = _suitability_checks()
        assert all(c["state"] == "pass" for c in checks), (
            f"All checks should pass: {[c['check_key'] for c in checks if c['state'] != 'pass']}"
        )

    @pytest.mark.parametrize(
        "overrides,check_key",
        [
            pytest.param(
                {"steady_speed": True},
                "SUITABILITY_CHECK_SPEED_VARIATION",
                id="speed_variation_steady",
            ),
            pytest.param(
                {"sensor_ids": {"s1"}},
                "SUITABILITY_CHECK_SENSOR_COVERAGE",
                id="sensor_coverage_below_3",
            ),
            pytest.param(
                {"sat_count": 5},
                "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
                id="saturation",
            ),
            pytest.param(
                {
                    "samples": [
                        {"client_id": "c1", "frames_dropped_total": 0},
                        {"client_id": "c1", "frames_dropped_total": 10},
                    ]
                },
                "SUITABILITY_CHECK_FRAME_INTEGRITY",
                id="frame_integrity_dropped",
            ),
            pytest.param(
                {"reference_complete": False},
                "SUITABILITY_CHECK_REFERENCE_COMPLETENESS",
                id="reference_incomplete",
            ),
        ],
    )
    def test_warn_condition(self, overrides: dict[str, Any], check_key: str) -> None:
        checks = _suitability_checks(**overrides)
        check = next(c for c in checks if c["check_key"] == check_key)
        assert check["state"] == "warn"
