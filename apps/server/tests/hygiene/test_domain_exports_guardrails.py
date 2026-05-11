"""Guardrails for domain exports and model completeness."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "name",
    [
        "FindingEvidence",
        "LocationHotspot",
        "ConfidenceAssessment",
        "SpeedProfile",
        "RunSuitability",
        "SuitabilityCheck",
    ],
)
def test_domain_value_objects_are_exported(name: str) -> None:
    """New domain value objects must be importable from ``vibesensor.domain``."""
    import importlib

    mod = importlib.import_module("vibesensor.domain")
    assert hasattr(mod, name), f"{name} must be exported from vibesensor.domain"


@pytest.mark.parametrize(
    "name",
    [
        "FindingEvidence",
        "LocationHotspot",
        "ConfidenceAssessment",
        "SpeedProfile",
        "RunSuitability",
        "SuitabilityCheck",
    ],
)
def test_domain_value_objects_are_frozen_dataclasses(name: str) -> None:
    """Domain value objects must be frozen dataclasses."""
    import dataclasses
    import importlib

    mod = importlib.import_module("vibesensor.domain")
    cls = getattr(mod, name)
    assert dataclasses.is_dataclass(cls), f"{name} must be a dataclass"


@pytest.mark.parametrize(
    "name",
    [
        "ConfigurationSnapshot",
        "DiagnosticCase",
        "DrivingSegment",
        "RecommendedAction",
        "Signature",
        "Symptom",
        "TestPlan",
        "TestRun",
        "VibrationOrigin",
    ],
)
def test_new_domain_objects_are_exported(name: str) -> None:
    import importlib

    mod = importlib.import_module("vibesensor.domain")
    assert hasattr(mod, name), f"{name} must be exported from vibesensor.domain"


_EXPECTED_DOMAIN_EXPORTS = [
    # Aggregates and entities
    "Car",
    "DiagnosticCase",
    "Run",
    "TestRun",
    # Value objects — car and context
    "CarSnapshot",
    "OrderReferenceSpec",
    "TireSpec",
    # Value objects — snapshots
    "AnalysisSettingsSnapshot",
    "DrivingPhaseSummary",
    "RunContextSnapshot",
    "SpeedProfileSummary",
    # Value objects — run and capture
    "ConfigurationSnapshot",
    "Measurement",
    "RunCapture",
    "RunSetup",
    "VibrationReading",
    # Value objects — findings and diagnostics
    "ConfidenceAssessment",
    "Finding",
    "FindingEvidence",
    "FindingKind",
    "LocationHotspot",
    "LocationIntensitySummary",
    "OrderMatchObservation",
    "Signature",
    "StrengthMetrics",
    "StrengthPeak",
    "VibrationOrigin",
    "VibrationSource",
    # Value objects — run context
    "DrivingPhase",
    "DrivingPhaseInterval",
    "DrivingPhaseSegment",
    "DrivingSegment",
    "RunStatus",
    "RunSuitability",
    "Sensor",
    "SensorPlacement",
    "SpeedProfile",
    "SpeedSource",
    "SpeedSourceKind",
    "SuitabilityCheck",
    "Symptom",
    # Test plan
    "RecommendedAction",
    "TestPlan",
    # Functions
    "RUN_TRANSITIONS",
    "plan_test_actions",
    "speed_band_sort_key",
    "speed_bin_label",
    "transition_run",
]


@pytest.mark.parametrize("name", _EXPECTED_DOMAIN_EXPORTS)
def test_all_domain_model_types_importable(name: str) -> None:
    """Every domain-model type must be importable from ``vibesensor.domain``."""
    import importlib

    mod = importlib.import_module("vibesensor.domain")
    assert hasattr(mod, name), f"{name} must be exported from vibesensor.domain"


def test_domain_exports_completeness() -> None:
    """``__all__`` in vibesensor.domain must cover every expected domain export."""
    import importlib

    mod = importlib.import_module("vibesensor.domain")
    all_names = set(getattr(mod, "__all__", []))
    missing = [n for n in _EXPECTED_DOMAIN_EXPORTS if n not in all_names]
    assert not missing, f"Missing from domain __all__: {missing}"
