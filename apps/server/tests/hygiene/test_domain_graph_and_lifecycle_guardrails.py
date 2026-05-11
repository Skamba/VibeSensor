"""Guardrails for the canonical domain graph and lifecycle mutability rules."""

from __future__ import annotations


def test_canonical_domain_graph_relationships() -> None:
    """Verify all canonical domain graph relationships exist as typed fields."""
    import dataclasses

    from vibesensor.domain import (
        Car,
        DiagnosticCase,
        DrivingSegment,
        Finding,
        Measurement,
        RunCapture,
        RunSetup,
        Sensor,
        SensorPlacement,
        Signature,
        SpeedSource,
        TestRun,
    )

    def field_type(cls: type, name: str) -> type:
        """Return the raw annotation for a dataclass field."""
        hints = {f.name: f for f in dataclasses.fields(cls)}
        assert name in hints, f"{cls.__name__} missing field {name}"
        return hints[name]

    # DiagnosticCase
    field_type(DiagnosticCase, "car")  # Car | None
    field_type(DiagnosticCase, "test_runs")  # tuple[TestRun, ...]

    # TestRun
    field_type(TestRun, "capture")  # RunCapture
    field_type(TestRun, "findings")  # tuple[Finding, ...]
    field_type(TestRun, "driving_segments")  # tuple[DrivingSegment, ...]

    # RunCapture
    field_type(RunCapture, "run_id")  # str (not a Run object — known deviation)
    field_type(RunCapture, "setup")  # RunSetup
    field_type(RunCapture, "measurements")  # tuple[Measurement, ...]
    assert not any(f.name == "run" for f in dataclasses.fields(RunCapture)), (
        "RunCapture must not hold a Run object reference (uses run_id: str)"
    )

    # RunSetup
    field_type(RunSetup, "sensors")  # tuple[Sensor, ...]
    field_type(RunSetup, "speed_source")  # SpeedSource

    # Sensor
    field_type(Sensor, "placement")  # SensorPlacement | None

    # Measurement
    field_type(Measurement, "sensor_id")  # str

    # Verify all imports are real classes (not just string names)
    for cls in (
        Car,
        DiagnosticCase,
        DrivingSegment,
        Finding,
        Measurement,
        RunCapture,
        RunSetup,
        Sensor,
        SensorPlacement,
        Signature,
        SpeedSource,
        TestRun,
    ):
        assert dataclasses.is_dataclass(cls), f"{cls.__name__} must be a dataclass"

    # Finding → finding-scoped value objects
    from vibesensor.domain import (
        ConfidenceAssessment,
        FindingEvidence,
        LocationHotspot,
        VibrationOrigin,
    )

    field_type(Finding, "confidence_assessment")  # ConfidenceAssessment | None
    field_type(Finding, "evidence")  # FindingEvidence | None
    field_type(Finding, "location")  # LocationHotspot | None (direct field, not via origin)
    field_type(Finding, "origin")  # VibrationOrigin | None (independent from location)

    for cls in (ConfidenceAssessment, FindingEvidence, LocationHotspot, VibrationOrigin):
        assert dataclasses.is_dataclass(cls), f"{cls.__name__} must be a dataclass"

    # RunStatus is associated with Run lifecycle
    from vibesensor.domain.run_status import RunStatus

    assert issubclass(RunStatus, str)  # StrEnum

    # DrivingPhase and DrivingSegment relationship
    field_type(DrivingSegment, "phase")  # DrivingPhase or equivalent


def test_finding_is_run_scoped() -> None:
    """Finding must not reference cross-run or case-level concepts directly."""
    import dataclasses

    from vibesensor.domain import Finding

    field_names = {f.name for f in dataclasses.fields(Finding)}
    # Finding is run-scoped: it must not hold case_id, diagnosis, or
    # cross-run aggregation fields.
    cross_run_indicators = {"case_id", "diagnosis", "diagnoses", "test_runs", "runs", "case"}
    leaked = field_names & cross_run_indicators
    assert not leaked, f"Finding has cross-run fields (must be run-scoped): {leaked}"


def test_lifecycle_mutability_rules() -> None:
    """Run is mutable (lifecycle object); RunCapture, RunSetup, TestRun are frozen."""
    import dataclasses

    from vibesensor.domain import RunCapture, RunSetup, TestRun
    from vibesensor.domain.run import Run

    # Run is the mutable lifecycle object during recording
    assert dataclasses.is_dataclass(Run)
    r = Run(run_id="mut-test")
    r.run_id = "mut-test-2"  # must not raise

    # Derived/immutable objects must be frozen
    for cls in (RunCapture, RunSetup, TestRun):
        assert dataclasses.is_dataclass(cls), f"{cls.__name__} must be a dataclass"
        frozen = cls.__dataclass_params__.frozen
        assert frozen, f"{cls.__name__} must be frozen (immutable once produced)"
