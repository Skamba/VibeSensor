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
    Aggregate root representing a complete diagnostic measurement session.
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
RunAnalysisResult
    Finalized analysis result — the domain aggregate.
SpeedProfile
    Run speed behaviour as a diagnostic concept.
RunSuitability
    Whether a run is trustworthy enough for diagnosis.
VibrationReading
    Value object representing a processed vibration measurement in dB.
"""

from .car import Car, TireSpec
from .confidence_assessment import ConfidenceAssessment
from .configuration_snapshot import ConfigurationSnapshot
from .diagnostic_case import DiagnosticCase
from .driving_phase import DrivingPhase
from .driving_segment import DrivingSegment
from .finding import (
    Finding,
    FindingKind,
    VibrationSource,
    speed_band_sort_key,
    speed_bin_label,
)
from .finding_evidence import FindingEvidence
from .hypothesis import Hypothesis, HypothesisStatus
from .location_hotspot import LocationHotspot
from .measurement import Measurement, VibrationReading
from .observation import Observation
from .recommended_action import RecommendedAction
from .report import Report
from .run import Run
from .run_analysis_result import RunAnalysisResult
from .run_status import RUN_TRANSITIONS, RunStatus, transition_run
from .run_suitability import RunSuitability, SuitabilityCheck
from .sensor import Sensor, SensorPlacement
from .signature import Signature
from .speed_profile import SpeedProfile
from .speed_source import SpeedSource, SpeedSourceKind
from .symptom import Symptom
from .test_plan import TestPlan
from .test_run import TestRun
from .vibration_origin import VibrationOrigin

__all__ = [
    # Primary domain names (prefer these)
    "Car",
    "ConfigurationSnapshot",
    "ConfidenceAssessment",
    "DiagnosticCase",
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
    "RunAnalysisResult",
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
