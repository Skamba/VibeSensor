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
    _build_phase_timeline,
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


class TestBuildPhaseTimeline:
    """Direct unit tests for _build_phase_timeline."""

    def test_empty_segments_returns_empty(self) -> None:
        assert _build_phase_timeline([], [], "en") == []

    def test_basic_segment_output(self) -> None:
        segs = [
            _FakeSeg(DrivingPhase.CRUISE, 0.0, 30.0, speed_min=40.0, speed_max=80.0),
            _FakeSeg(DrivingPhase.ACCELERATION, 30.0, 45.0, speed_min=40.0, speed_max=80.0),
        ]
        findings: list[dict[str, object]] = [
            {
                "finding_id": "F001",
                "confidence_0_to_1": 0.60,
                "phase_evidence": {"phases_detected": ["cruise"]},
            }
        ]
        entries = _build_phase_timeline(segs, findings, "en")
        assert len(entries) == 2
        assert entries[0]["phase"] == "cruise"
        assert entries[0]["has_fault_evidence"] is True
        assert entries[1]["has_fault_evidence"] is False

    @pytest.mark.parametrize(
        "finding",
        [
            pytest.param(
                {
                    "finding_id": "REF_SPEED",
                    "confidence_0_to_1": 0.90,
                    "phase_evidence": {"phases_detected": ["cruise"]},
                },
                id="ref_finding_ignored",
            ),
            pytest.param(
                {
                    "finding_id": "F001",
                    "confidence_0_to_1": 0.01,
                    "phase_evidence": {"phases_detected": ["cruise"]},
                },
                id="low_confidence_ignored",
            ),
        ],
    )
    def test_finding_does_not_mark_phase(self, finding: dict[str, object]) -> None:
        """REF_ findings and below-threshold findings should not contribute."""
        entries = _build_phase_timeline([_FakeSeg()], [finding], "en")
        assert entries[0]["has_fault_evidence"] is False
