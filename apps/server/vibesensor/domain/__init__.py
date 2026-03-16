"""Domain model package — rich, DDD-aligned value objects and aggregates.

This package exposes the core domain types for vibration diagnostics,
strictly decoupled from FastAPI, UDP transport, or persistence concerns.

Consumers should import from ``vibesensor.domain`` rather than from
individual module files.

Primary domain concepts
-----------------------
Car
    The vehicle under test.
Sensor
    A physical accelerometer node attached to the vehicle.
Run
    Mutable capture lifecycle for one diagnostic measurement run.
RunCapture
    Immutable captured evidence from one completed Run.
TestRun
    Run-level diagnostic aggregate (findings, top causes, segments).
DiagnosticCase
    Case-level aggregate for one investigation episode.
Finding
    One diagnostic conclusion or cause candidate.
Signature
    A meaningful vibration pattern label attached to a finding.
Measurement
    Value object representing a single multi-axis acceleration sample.
SpeedSource
    How vehicle speed is obtained during a run.
SpeedProfile
    Run speed behaviour as a diagnostic concept.
RunSuitability
    Whether a run is trustworthy enough for diagnosis.
"""

from .car import Car, TireSpec
from .confidence_assessment import ConfidenceAssessment
from .diagnostic_case import DiagnosticCase, Symptom
from .driving_segment import DrivingPhase, DrivingSegment
from .finding import (
    Finding,
    FindingEvidence,
    FindingKind,
    Signature,
    VibrationSource,
    speed_band_sort_key,
    speed_bin_label,
)
from .location_hotspot import LocationHotspot
from .run import Run
from .run_capture import ConfigurationSnapshot, Measurement, RunCapture, RunSetup, VibrationReading
from .run_status import RUN_TRANSITIONS, RunStatus, transition_run
from .run_suitability import RunSuitability, SuitabilityCheck
from .sensor import Sensor, SensorPlacement
from .speed_profile import SpeedProfile
from .speed_source import SpeedSource, SpeedSourceKind
from .test_plan import RecommendedAction, TestPlan, plan_test_actions
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
    "LocationHotspot",
    "Measurement",
    "RecommendedAction",
    "RUN_TRANSITIONS",
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
    # Service functions
    "plan_test_actions",
    # Existing names
    "VibrationReading",
]
