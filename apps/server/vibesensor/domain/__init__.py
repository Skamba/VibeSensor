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

from ._numeric import coerce_float, coerce_int
from .analysis_settings import AnalysisSettingsSnapshot
from .capture_readiness import CaptureReadiness, CaptureReadinessCheck, CaptureReadinessPolicy
from .car import Car, CarOrderReferenceSourceStatus, CarOrderReferenceStatus, CarSnapshot
from .confidence_assessment import ConfidenceAssessment
from .diagnosis_assessment import (
    DIAGNOSIS_AMBIGUOUS_SCORE_GAP,
    DIAGNOSIS_CLOSE_ALTERNATIVE_REEVALUATION_GAP,
    DiagnosisAssessment,
    DiagnosisAssessmentFactor,
    DiagnosisAssessmentFactorDetails,
    DiagnosisAssessmentInputs,
    apply_diagnosis_assessment_fallback,
    diagnosis_assessment_from_components,
    score_diagnosis_assessment_inputs,
)
from .diagnostic_case import DiagnosticCase, Symptom
from .driving_phase_summary import DrivingPhaseSummary
from .driving_segment import DrivingPhase, DrivingPhaseInterval, DrivingPhaseSegment, DrivingSegment
from .finding import Finding, speed_band_sort_key, speed_bin_label
from .finding_evidence import FindingEvidence, Signature
from .finding_types import FindingKind, VibrationSource
from .location_hotspot import (
    LocationHotspot,
    LocationHotspotRow,
    LocationIntensitySummary,
    PhaseIntensitySummary,
    StrengthBucketDistribution,
)
from .order_match import OrderMatchObservation
from .order_reference import OrderReferenceSpec
from .run import Run
from .run_capture import ConfigurationSnapshot, Measurement, RunCapture, RunSetup, VibrationReading
from .run_context import RunContextSnapshot
from .run_status import RUN_TRANSITIONS, RunStatus, is_run_deletable, transition_run
from .run_suitability import RunSuitability, SuitabilityCheck
from .sensor import Sensor, SensorPlacement, normalize_sensor_id
from .speed_profile import SpeedProfile
from .speed_profile_summary import SpeedProfileSummary
from .speed_source import SpeedSource, SpeedSourceKind
from .strength_metrics import StrengthMetrics, StrengthPeak
from .test_plan import RecommendedAction, TestPlan, plan_test_actions
from .test_run import TestRun
from .tire_spec import TireSpec
from .vehicle_configuration import (
    VehicleConfiguration,
    VehicleConfigurationField,
    VehicleConfigurationSourceStatus,
    VehicleConfigurationTireOption,
    VehicleDrivetrain,
    VehicleFieldConfidence,
    VehicleFieldProvenance,
    VehicleFuelType,
)
from .vibration_origin import VibrationOrigin

__all__ = [
    # Aggregates and entities
    "Car",
    "CarOrderReferenceSourceStatus",
    "CarOrderReferenceStatus",
    "CaptureReadiness",
    "CaptureReadinessCheck",
    "CaptureReadinessPolicy",
    "DiagnosticCase",
    "Run",
    "TestRun",
    # Value objects — car and context
    "CarSnapshot",
    "OrderReferenceSpec",
    "TireSpec",
    "VehicleConfiguration",
    "VehicleConfigurationField",
    "VehicleConfigurationSourceStatus",
    "VehicleConfigurationTireOption",
    "VehicleDrivetrain",
    "VehicleFieldConfidence",
    "VehicleFieldProvenance",
    "VehicleFuelType",
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
    "DiagnosisAssessment",
    "DiagnosisAssessmentFactor",
    "DiagnosisAssessmentFactorDetails",
    "DiagnosisAssessmentInputs",
    "Finding",
    "FindingEvidence",
    "FindingKind",
    "LocationHotspot",
    "LocationHotspotRow",
    "LocationIntensitySummary",
    "OrderMatchObservation",
    "PhaseIntensitySummary",
    "Signature",
    "StrengthBucketDistribution",
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
    "DIAGNOSIS_AMBIGUOUS_SCORE_GAP",
    "DIAGNOSIS_CLOSE_ALTERNATIVE_REEVALUATION_GAP",
    "apply_diagnosis_assessment_fallback",
    "coerce_float",
    "coerce_int",
    "diagnosis_assessment_from_components",
    "is_run_deletable",
    "normalize_sensor_id",
    "plan_test_actions",
    "score_diagnosis_assessment_inputs",
    "speed_band_sort_key",
    "speed_bin_label",
    "transition_run",
]
