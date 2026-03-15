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

from vibesensor.domain.car import Car, TireSpec
from vibesensor.domain.confidence_assessment import ConfidenceAssessment
from vibesensor.domain.configuration_snapshot import ConfigurationSnapshot
from vibesensor.domain.diagnosis import Diagnosis
from vibesensor.domain.diagnostic_case import DiagnosticCase, DiagnosticCaseEpistemicRule
from vibesensor.domain.diagnostic_reasoning import DiagnosticReasoning
from vibesensor.domain.driving_phase import DrivingPhase
from vibesensor.domain.driving_segment import DrivingSegment
from vibesensor.domain.finding import (
    Finding,
    FindingKind,
    VibrationSource,
    speed_band_sort_key,
    speed_bin_label,
)
from vibesensor.domain.finding_evidence import FindingEvidence
from vibesensor.domain.hypothesis import Hypothesis, HypothesisStatus
from vibesensor.domain.location_hotspot import LocationHotspot
from vibesensor.domain.measurement import Measurement, VibrationReading
from vibesensor.domain.observation import Observation
from vibesensor.domain.recommended_action import RecommendedAction
from vibesensor.domain.report import Report
from vibesensor.domain.run import Run
from vibesensor.domain.run_capture import RunCapture
from vibesensor.domain.run_setup import RunSetup
from vibesensor.domain.run_status import RUN_TRANSITIONS, RunStatus, transition_run
from vibesensor.domain.run_suitability import RunSuitability, SuitabilityCheck
from vibesensor.domain.sensor import Sensor, SensorPlacement
from vibesensor.domain.signature import Signature
from vibesensor.domain.speed_profile import SpeedProfile
from vibesensor.domain.speed_source import SpeedSource, SpeedSourceKind
from vibesensor.domain.symptom import Symptom
from vibesensor.domain.test_plan import TestPlan
from vibesensor.domain.test_run import TestRun
from vibesensor.domain.vibration_origin import VibrationOrigin

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
