"""Whole-run fused diagnosis contracts for persisted summaries and exemplars.

These compact contracts sit above the whole-run context, order, and spatial
summary layers. They intentionally define the diagnosis shell, ambiguity flags,
fallback markers, and exemplar references before later issues settle the stable
support/counterevidence factor vocabulary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from vibesensor.common.json_contract import (
    JsonContract,
    require_non_empty_text,
    require_non_negative,
)
from vibesensor.domain.diagnosis_assessment import DiagnosisAssessmentFactor
from vibesensor.summary.spatial_evidence_contracts import LocationProofBasis

__all__ = [
    "DiagnosisDataQualityLimitation",
    "DiagnosisExemplarKind",
    "DiagnosisExemplarReference",
    "DiagnosisDataQualitySummary",
    "DiagnosisFactor",
    "DiagnosisFactorDetails",
    "DiagnosisFactorKey",
    "DiagnosisFactorPolarity",
    "DiagnosisFactorSeverity",
    "WholeRunDiagnosisDataBasis",
    "WholeRunDiagnosisSummary",
    "diagnosis_factor_from_assessment",
]

type DiagnosisExemplarKind = Literal[
    "order_support_interval",
    "whole_run_context_interval",
    "spatial_location",
]
type DiagnosisFactorKey = Literal[
    "raw_backed",
    "repeated_support",
    "sustained_support",
    "stable_frequency",
    "tight_order_lock",
    "localized_support",
    "clean_signal",
    "user_confirmed_vehicle_data",
    "summary_only",
    "raw_replay_incomplete",
    "legacy_context",
    "speed_context_gaps",
    "rpm_context_gaps",
    "sparse_support",
    "brief_support",
    "drifting_frequency",
    "loose_order_lock",
    "mixed_support_locations",
    "noisy_signal",
    "weak_spatial",
    "close_alternative",
    "incomplete_reference",
    "secondary_vehicle_data",
    "approximate_vehicle_data",
    "unverified_vehicle_data",
]
type DiagnosisDataQualityLimitation = Literal[
    "reference_gap",
    "speed_context",
    "sensor_timing",
    "sensor_mounting",
    "sensor_clipping",
    "road_shock",
    "weak_spatial",
    "ambiguous_location",
    "summary_fallback",
    "window_quality",
]
type DiagnosisFactorPolarity = Literal["support", "counterevidence"]
type DiagnosisFactorSeverity = Literal["low", "medium", "high"]
type WholeRunDiagnosisDataBasis = Literal["raw_backed", "partial_raw_backed", "summary_only"]


@dataclass(frozen=True, slots=True)
class DiagnosisExemplarReference(JsonContract):
    """Compact reference to one persisted exemplar for a fused diagnosis."""

    kind: DiagnosisExemplarKind
    order_hypothesis_key: str | None = None
    support_interval_index: int | None = None
    spatial_candidate_key: str | None = None
    context_segment_index: int | None = None
    location: str | None = None
    phase: str | None = None
    speed_band: str | None = None

    def __post_init__(self) -> None:
        if self.kind == "order_support_interval":
            require_non_empty_text(self, "order_hypothesis_key")
        elif self.kind == "whole_run_context_interval":
            if self.context_segment_index is None:
                raise ValueError("context_segment_index is required for whole_run_context_interval")
        elif self.kind == "spatial_location":
            require_non_empty_text(self, "spatial_candidate_key", "location")
        require_non_negative(self, "support_interval_index", "context_segment_index")


@dataclass(frozen=True, slots=True)
class DiagnosisFactorDetails(JsonContract):
    """Structured details carried by one persisted diagnosis factor row."""

    raw_backed_sample_count: int | None = None
    supporting_window_count: int | None = None
    supporting_duration_s: float | None = None
    stable_frequency_min_hz: float | None = None
    stable_frequency_max_hz: float | None = None
    frequency_span_hz: float | None = None
    supporting_location_count: int | None = None
    top_support_location: str | None = None
    top_support_share: float | None = None
    mean_relative_error: float | None = None
    snr_db: float | None = None
    alternative_source: str | None = None
    speed_gap_window_count: int | None = None
    rpm_gap_window_count: int | None = None
    fallback_reason: str | None = None
    car_data_reference_scope: str | None = None
    car_data_confidence: str | None = None

    def __post_init__(self) -> None:
        require_non_negative(
            self,
            "raw_backed_sample_count",
            "supporting_window_count",
            "supporting_location_count",
            "speed_gap_window_count",
            "rpm_gap_window_count",
        )


@dataclass(frozen=True, slots=True)
class DiagnosisFactor(JsonContract):
    """One stable support or counterevidence factor for a fused diagnosis."""

    factor_key: DiagnosisFactorKey
    polarity: DiagnosisFactorPolarity
    severity: DiagnosisFactorSeverity
    weight: float
    details: DiagnosisFactorDetails = DiagnosisFactorDetails()

    def __post_init__(self) -> None:
        require_non_negative(self, "weight")


def diagnosis_factor_from_assessment(factor: DiagnosisAssessmentFactor) -> DiagnosisFactor:
    """Project one domain assessment factor onto the persisted factor contract."""
    return DiagnosisFactor.from_mapping(asdict(factor))


@dataclass(frozen=True, slots=True)
class DiagnosisDataQualitySummary(JsonContract):
    """Compact persisted data-quality rollup for one fused diagnosis."""

    usable_window_count: int | None = None
    limited_window_count: int | None = None
    excluded_window_count: int | None = None
    mean_quality_score: float | None = None
    speed_context_limited_window_count: int = 0
    sensor_timing_integrity_window_count: int = 0
    sensor_mounting_artifact_window_count: int = 0
    sensor_clipping_window_count: int = 0
    shock_transient_window_count: int = 0
    limitation_keys: tuple[DiagnosisDataQualityLimitation, ...] = ()

    def __post_init__(self) -> None:
        require_non_negative(
            self,
            "usable_window_count",
            "limited_window_count",
            "excluded_window_count",
            "speed_context_limited_window_count",
            "sensor_timing_integrity_window_count",
            "sensor_mounting_artifact_window_count",
            "sensor_clipping_window_count",
            "shock_transient_window_count",
        )


@dataclass(frozen=True, slots=True)
class WholeRunDiagnosisSummary(JsonContract):
    """Compact persisted/report-facing summary for one fused whole-run diagnosis."""

    diagnosis_key: str
    suspected_source: str
    rank: int
    data_basis: WholeRunDiagnosisDataBasis
    support_score: float | None = None
    counterevidence_score: float | None = None
    total_score: float | None = None
    order_hypothesis_key: str | None = None
    spatial_candidate_key: str | None = None
    location_proof_basis: LocationProofBasis | None = None
    supporting_window_count: int | None = None
    supporting_duration_s: float | None = None
    supporting_sensor_count: int | None = None
    stable_frequency_min_hz: float | None = None
    stable_frequency_max_hz: float | None = None
    dominant_location: str | None = None
    runner_up_location: str | None = None
    dominant_phase: str | None = None
    dominant_speed_band: str | None = None
    location_separation_db: float | None = None
    dominance_ratio: float | None = None
    alternative_source: str | None = None
    confidence_gap_to_alternative: float | None = None
    ambiguous_diagnosis: bool = False
    ambiguous_location: bool = False
    suspicious: bool = False
    weak_spatial_separation: bool = False
    has_reference_gap: bool = False
    uses_summary_fallback: bool = False
    fallback_reason: str | None = None
    data_quality_summary: DiagnosisDataQualitySummary = DiagnosisDataQualitySummary()
    exemplar_references: tuple[DiagnosisExemplarReference, ...] = ()
    support_factors: tuple[DiagnosisFactor, ...] = ()
    counterevidence_factors: tuple[DiagnosisFactor, ...] = ()

    def __post_init__(self) -> None:
        require_non_empty_text(self, "diagnosis_key", "suspected_source")
        require_non_negative(self, "rank", "supporting_window_count", "supporting_sensor_count")
