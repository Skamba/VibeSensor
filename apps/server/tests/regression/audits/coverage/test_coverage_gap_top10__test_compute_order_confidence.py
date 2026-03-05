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

from vibesensor.analysis.findings import (
    _compute_order_confidence,
)
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


class TestComputeOrderConfidence:
    """Direct unit tests for _compute_order_confidence."""

    _DEFAULTS: dict[str, Any] = {
        "effective_match_rate": 0.60,
        "error_score": 0.80,
        "corr_val": 0.50,
        "snr_score": 0.60,
        "absolute_strength_db": 20.0,
        "localization_confidence": 0.70,
        "weak_spatial_separation": False,
        "dominance_ratio": 2.0,
        "constant_speed": False,
        "steady_speed": False,
        "matched": 30,
        "corroborating_locations": 2,
        "phases_with_evidence": 2,
        "is_diffuse_excitation": False,
        "diffuse_penalty": 1.0,
        "n_connected_locations": 3,
        "no_wheel_sensors": False,
        "path_compliance": 1.0,
    }

    @classmethod
    def _call(cls, **overrides: Any) -> float:
        return _compute_order_confidence(**{**cls._DEFAULTS, **overrides})

    def test_baseline_returns_moderate_confidence(self) -> None:
        conf = self._call()
        assert 0.30 < conf < 0.90, f"Baseline defaults produced unexpected {conf}"

    def test_output_clamped_low(self) -> None:
        """All-zero inputs should clamp to the 0.08 floor."""
        conf = self._call(
            effective_match_rate=0.0,
            error_score=0.0,
            corr_val=0.0,
            snr_score=0.0,
            absolute_strength_db=0.0,
            localization_confidence=0.0,
            matched=0,
            corroborating_locations=0,
            phases_with_evidence=0,
        )
        assert conf == pytest.approx(0.08, abs=0.001)

    def test_output_clamped_high(self) -> None:
        """Perfect inputs should clamp to the 0.97 ceiling."""
        conf = self._call(
            effective_match_rate=1.0,
            error_score=1.0,
            corr_val=1.0,
            snr_score=1.0,
            absolute_strength_db=40.0,
            localization_confidence=1.0,
            matched=100,
            corroborating_locations=4,
            phases_with_evidence=4,
        )
        assert conf == pytest.approx(0.97, abs=0.001)

    def test_negligible_strength_caps_at_045(self) -> None:
        """absolute_strength_db below negligible threshold should cap confidence."""
        conf = self._call(absolute_strength_db=5.0)
        assert conf <= 0.45 + 0.001

    @pytest.mark.parametrize(
        "normal_kw,penalty_kw",
        [
            pytest.param(
                {"weak_spatial_separation": False},
                {"weak_spatial_separation": True},
                id="weak_spatial_separation",
            ),
            pytest.param(
                {"constant_speed": False},
                {"constant_speed": True},
                id="constant_speed",
            ),
            pytest.param(
                {"is_diffuse_excitation": False},
                {"is_diffuse_excitation": True, "diffuse_penalty": 0.75},
                id="diffuse_excitation",
            ),
            pytest.param(
                {"n_connected_locations": 3},
                {"n_connected_locations": 1},
                id="single_sensor",
            ),
            pytest.param(
                {"absolute_strength_db": 25.0},
                {"absolute_strength_db": 12.0},
                id="light_strength_band",
            ),
        ],
    )
    def test_penalty_reduces_confidence(
        self, normal_kw: dict[str, Any], penalty_kw: dict[str, Any]
    ) -> None:
        assert self._call(**penalty_kw) < self._call(**normal_kw)

    def test_path_compliance_shifts_weights(self) -> None:
        """Higher path_compliance should shift weight from corr to match."""
        stiff = self._call(path_compliance=1.0, corr_val=0.0, effective_match_rate=0.80)
        compliant = self._call(path_compliance=1.5, corr_val=0.0, effective_match_rate=0.80)
        assert compliant >= stiff - 0.02

    def test_corroborating_locations_boost(self) -> None:
        base = self._call(corroborating_locations=1)
        boosted = self._call(corroborating_locations=3)
        assert boosted > base, "3+ corroborating locations should boost confidence"
