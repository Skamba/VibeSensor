"""Domain model guardrails for graph relationships and typed-concept conformance.

Covers the migration-plan seams that this file still enforces directly: T03 and T07.
"""

from __future__ import annotations

import dataclasses

import pytest

from vibesensor.domain import (
    AnalysisSettingsSnapshot,
    CarSnapshot,
    DiagnosticCase,
    DrivingPhaseInterval,
    DrivingPhaseSegment,
    DrivingPhaseSummary,
    DrivingSegment,
    LocationIntensitySummary,
    OrderMatchObservation,
    OrderReferenceSpec,
    RunCapture,
    RunContextSnapshot,
    RunSetup,
    SpeedProfileSummary,
    StrengthMetrics,
    StrengthPeak,
    TestRun,
    TireSpec,
)

# ---------------------------------------------------------------------------
# T03 — Domain graph relationships
# ---------------------------------------------------------------------------


class TestDomainGraphRelationships:
    """Verify canonical containment/reference relationships (T03)."""

    def test_diagnostic_case_contains_test_runs_and_car(self) -> None:
        """DiagnosticCase → TestRun*, scopes 0-or-1 Car."""
        hints = {f.name: f.type for f in dataclasses.fields(DiagnosticCase)}
        assert "test_runs" in hints
        assert "car" in hints

    def test_test_run_contains_capture_segments_findings(self) -> None:
        """TestRun → RunCapture, DrivingSegment*, Finding*."""
        hints = {f.name: f.type for f in dataclasses.fields(TestRun)}
        assert "capture" in hints
        assert "driving_segments" in hints
        assert "findings" in hints

    def test_run_capture_references_run_and_contains_setup(self) -> None:
        """RunCapture → Run (by id), RunSetup, Measurement*."""
        hints = {f.name: f.type for f in dataclasses.fields(RunCapture)}
        assert "run_id" in hints
        assert "setup" in hints
        assert "measurements" in hints

    def test_run_setup_contains_sensors_and_speed_source(self) -> None:
        """RunSetup → Sensor*, SpeedSource."""
        hints = {f.name: f.type for f in dataclasses.fields(RunSetup)}
        assert "sensors" in hints
        assert "speed_source" in hints

    def test_strength_metrics_contains_strength_peaks(self) -> None:
        """StrengthMetrics → StrengthPeak values."""
        hints = {f.name: f.type for f in dataclasses.fields(StrengthMetrics)}
        peak_fields = [n for n, t in hints.items() if "StrengthPeak" in str(t)]
        assert len(peak_fields) >= 1

    def test_analysis_settings_does_not_co_own_order_reference(self) -> None:
        """AnalysisSettingsSnapshot does NOT co-own OrderReferenceSpec."""
        hints = {f.name: f.type for f in dataclasses.fields(AnalysisSettingsSnapshot)}
        # It may have a computed property but not a stored field
        assert "order_reference_spec" not in hints


# ---------------------------------------------------------------------------
# T07 — Existing typed internal concepts conform
# ---------------------------------------------------------------------------

_FROZEN_DOMAIN_TYPES = [
    AnalysisSettingsSnapshot,
    CarSnapshot,
    DrivingPhaseInterval,
    DrivingPhaseSegment,
    DrivingPhaseSummary,
    DrivingSegment,
    LocationIntensitySummary,
    OrderMatchObservation,
    OrderReferenceSpec,
    RunContextSnapshot,
    SpeedProfileSummary,
    StrengthMetrics,
    StrengthPeak,
    TireSpec,
]


class TestTypedConceptsConform:
    """Verify all existing typed internal concepts are frozen dataclasses with __slots__ (T07)."""

    @pytest.mark.parametrize("cls", _FROZEN_DOMAIN_TYPES, ids=lambda c: c.__name__)
    def test_is_frozen_dataclass(self, cls: type) -> None:
        assert dataclasses.is_dataclass(cls), f"{cls.__name__} must be a dataclass"
        # frozen=True sets __dataclass_params__.frozen
        params = getattr(cls, "__dataclass_params__", None)
        assert params is not None and params.frozen, f"{cls.__name__} must use frozen=True"

    @pytest.mark.parametrize("cls", _FROZEN_DOMAIN_TYPES, ids=lambda c: c.__name__)
    def test_has_slots(self, cls: type) -> None:
        assert hasattr(cls, "__slots__"), f"{cls.__name__} must use slots=True"
