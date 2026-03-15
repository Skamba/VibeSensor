"""Domain model package — rich, DDD-aligned value objects and aggregates.

This package exposes the core domain types for vibration diagnostics,
strictly decoupled from FastAPI, UDP transport, or persistence concerns.

Each primary domain object lives in its own dedicated file.  Consumers
should import from ``vibesensor.domain`` rather than from individual
module files.

Primary domain concepts
-----------------------
Car
    The vehicle under test.
Sensor
    A physical accelerometer node attached to the vehicle.
SensorPlacement
    A sensor's mounting position on the vehicle.
Run
    Mutable capture lifecycle for one diagnostic measurement run.
RunCapture
    Immutable captured evidence from one completed Run.
DiagnosticReasoning
    Run-scoped reasoning model (observations, signatures, hypotheses).
Measurement
    Value object representing a single multi-axis acceleration sample.
SpeedSource
    How vehicle speed is obtained during a run.
Finding
    One diagnostic conclusion or cause candidate.
FindingEvidence
    Structured evidence supporting a finding.
LocationHotspot
    Where vibration evidence is spatially concentrated.
ConfidenceAssessment
    Why confidence in a finding is high, low, or withheld.
Report
    The assembled output of a diagnostic run.
SpeedProfile
    Run speed behaviour as a diagnostic concept.
RunSuitability
    Whether a run is trustworthy enough for diagnosis.
VibrationReading
    Value object representing a processed vibration measurement in dB.
"""

from .diagnostics import (
    ConfidenceAssessment,
    Diagnosis,
    DiagnosticCase,
    DiagnosticCaseEpistemicRule,
    DiagnosticReasoning,
    Finding,
    FindingEvidence,
    FindingKind,
    Hypothesis,
    HypothesisStatus,
    LocationHotspot,
    Observation,
    RecommendedAction,
    RunSuitability,
    Signature,
    SpeedProfile,
    SuitabilityCheck,
    Symptom,
    TestPlan,
    VibrationOrigin,
    VibrationSource,
    speed_band_sort_key,
    speed_bin_label,
)
from .reporting import Report
from .run import RUN_TRANSITIONS, Run, RunCapture, RunSetup, RunStatus, TestRun, transition_run
from .sensing import (
    ConfigurationSnapshot,
    DrivingPhase,
    DrivingSegment,
    Measurement,
    Sensor,
    SensorPlacement,
    SpeedSource,
    SpeedSourceKind,
    VibrationReading,
)
from .vehicle import Car, TireSpec

__all__ = [
    # Primary domain names (prefer these)
    "Car",
    "ConfigurationSnapshot",
    "ConfidenceAssessment",
    "Diagnosis",
    "DiagnosticCase",
    "DiagnosticCaseEpistemicRule",
    "DiagnosticReasoning",
    "DrivingSegment",
    "DrivingPhase",
    "Finding",
    "FindingEvidence",
    "FindingKind",
    "Hypothesis",
    "HypothesisStatus",
    "LocationHotspot",
    "Measurement",
    "Observation",
    "RecommendedAction",
    "RUN_TRANSITIONS",
    "Report",
    "Run",
    "RunCapture",
    "RunSetup",
    "RunStatus",
    "RunSuitability",
    "Sensor",
    "SensorPlacement",
    "Signature",
    "SpeedProfile",
    "speed_band_sort_key",
    "speed_bin_label",
    "SpeedSource",
    "SpeedSourceKind",
    "Symptom",
    "SuitabilityCheck",
    "TestPlan",
    "TestRun",
    "TireSpec",
    "VibrationSource",
    "VibrationOrigin",
    "transition_run",
    # Existing names
    "VibrationReading",
]
