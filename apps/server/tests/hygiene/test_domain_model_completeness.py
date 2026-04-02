"""Verify all domain objects from docs/domain-model.md are exported.

This test prevents regressions where domain objects are deleted or renamed
without updating the document or the package exports.
"""

from __future__ import annotations

import vibesensor.domain as domain

# Objects listed in docs/domain-model.md § "Concept categories"
# Core diagnostic aggregates and entities + Supporting typed internal concepts

_REQUIRED_DOMAIN_EXPORTS = [
    # Core diagnostic aggregates and entities
    "DiagnosticCase",
    "TestRun",
    "Finding",
    "Run",
    "RunCapture",
    "RunSetup",
    "Car",
    "DrivingSegment",
    "DrivingPhase",
    "Measurement",
    "Sensor",
    "SensorPlacement",
    "SpeedSource",
    "Symptom",
    "TestPlan",
    "RecommendedAction",
    "SpeedProfile",
    "RunSuitability",
    "SuitabilityCheck",
    "ConfigurationSnapshot",
    "ConfidenceAssessment",
    "FindingEvidence",
    "LocationHotspot",
    "VibrationOrigin",
    # Domain enums and value objects (already exported, now tracked)
    "VibrationSource",
    "FindingKind",
    "SpeedSourceKind",
    "TireSpec",
    "Signature",
    "VibrationReading",
    # Supporting typed internal concepts
    "OrderReferenceSpec",
    "AnalysisSettingsSnapshot",
    "CarSnapshot",
    "RunContextSnapshot",
    "StrengthMetrics",
    "StrengthPeak",
    "SpeedProfileSummary",
    "DrivingPhaseSummary",
    # New typed internal concepts (Phase A creates these)
    "OrderMatchObservation",
    "DrivingPhaseInterval",
    "DrivingPhaseSegment",
    "LocationIntensitySummary",
    # Lifecycle and support
    "RunStatus",
    "RUN_TRANSITIONS",
    "transition_run",
    "plan_test_actions",
]


def test_all_documented_domain_objects_are_exported() -> None:
    """Every object listed in docs/domain-model.md must be in vibesensor.domain exports."""
    missing = [name for name in _REQUIRED_DOMAIN_EXPORTS if not hasattr(domain, name)]
    assert not missing, (
        f"Domain objects listed in docs/domain-model.md but missing from "
        f"vibesensor.domain exports: {missing}"
    )


def test_domain_exports_match_all_list() -> None:
    """vibesensor.domain.__all__ must include all documented objects."""
    all_exports = set(domain.__all__)
    missing = [name for name in _REQUIRED_DOMAIN_EXPORTS if name not in all_exports]
    assert not missing, f"Domain objects missing from vibesensor.domain.__all__: {missing}"
