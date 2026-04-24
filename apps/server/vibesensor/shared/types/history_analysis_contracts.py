"""Shared analysis/history summary contracts reused by boundary and HTTP layers.

These TypedDicts are the canonical outward owners for analysis/history summary
wrapper and composite contracts used by summary-boundary serializers and the
HTTP/OpenAPI response schema. ``AnalysisSummary``,
``AnalysisSummaryCoreResponse``, and ``AnalysisSummaryResponse`` are defined
here, while ``FindingPayload`` remains the canonical shared outward finding
wrapper re-exported from ``finding_payload_parts`` so its internal core versus
presentation split can evolve without broadening this module's direct field
ownership. Endpoint-specific HTTP wrappers remain local to
``shared.types.api_models.history``. Persisted storage payloads should use the
separate contracts in ``persisted_analysis_contracts``.
"""

from __future__ import annotations

from typing import Any, Literal, Required, TypedDict

from pydantic import ConfigDict

from vibesensor.shared.types.analysis_views import (
    PhaseSpeedBreakdownRow,
    PlotDataResult,
    SpeedBreakdownRow,
)
from vibesensor.shared.types.data_quality_contracts import (
    DataQualityAccelSanityResponse,
    DataQualityOutliersResponse,
    DataQualityRequiredMissingPctResponse,
    DataQualityResponse,
    DataQualitySpeedCoverageResponse,
    OutlierSummaryResponse,
)
from vibesensor.shared.types.finding_payload_parts import AmplitudeMetric, FindingPayload
from vibesensor.shared.types.json_types import (
    JsonSchemaObject,
    JsonSchemaValue,
)

__all__ = [
    "AmplitudeMetric",
    "AnalysisSummary",
    "AnalysisSummaryCoreResponse",
    "AnalysisSummaryResponse",
    "DataQualityAccelSanityResponse",
    "DataQualityOutliersResponse",
    "DataQualityRequiredMissingPctResponse",
    "DataQualityResponse",
    "DataQualitySpeedCoverageResponse",
    "DiagnosisFactorDetailsResponse",
    "DiagnosisFactorKey",
    "DiagnosisFactorPolarity",
    "DiagnosisFactorResponse",
    "DiagnosisFactorSeverity",
    "FindingPayload",
    "DiagnosisExemplarKind",
    "DiagnosisExemplarReferenceResponse",
    "LocationIntensitySummaryResponse",
    "LocationProofBasis",
    "WholeRunDiagnosisDataBasis",
    "WholeRunDiagnosisSummaryResponse",
    "OutlierSummaryResponse",
    "OrderHarmonicEvidenceSummaryResponse",
    "OrderTracePhaseSupportResponse",
    "OrderTraceSummaryResponse",
    "OrderTraceSupportIntervalResponse",
    "PayloadObject",
    "PayloadValue",
    "PhaseInfoResponse",
    "PhaseIntensityStatsResponse",
    "PhaseSegmentSummaryResponse",
    "PhaseTimelineEntryResponse",
    "RunSuitabilityCheck",
    "SpeedStatsResponse",
    "StrengthBucketDistributionResponse",
    "SummaryWarningResponse",
    "SuspectedVibrationOriginPayload",
    "SpatialEvidenceSummaryResponse",
    "SpatialLocationSummaryResponse",
    "TestPlanStepResponse",
    "WholeRunContextIntervalResponse",
]

type PayloadObject = JsonSchemaObject
type PayloadValue = JsonSchemaValue
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
]
type DiagnosisFactorPolarity = Literal["support", "counterevidence"]
type DiagnosisFactorSeverity = Literal["low", "medium", "high"]
type WholeRunDiagnosisDataBasis = Literal["raw_backed", "partial_raw_backed", "summary_only"]
type LocationProofBasis = Literal[
    "whole_run_summary",
    "supporting_windows_raw_backed",
    "supporting_windows_summary_only",
]


_FORBID_EXTRA_TYPEDDICT_CONFIG = ConfigDict(extra="forbid")
_IGNORE_EXTRA_TYPEDDICT_CONFIG = ConfigDict(extra="ignore")


class RunSuitabilityCheck(TypedDict, total=False):
    """Typed HTTP contract for one run-suitability diagnostic check."""

    check_key: Required[str]
    state: Required[str]
    explanation: PayloadValue


class SummaryWarningResponse(TypedDict, total=False):
    """Response body for a persisted summary warning before localization."""

    code: Required[str]
    severity: Required[Literal["warn", "error"]]
    applies_to: Required[str]
    title: Required[PayloadValue]
    detail: PayloadValue


class TestPlanStepResponse(TypedDict):
    """Response body for one recommended next-step action."""

    action_id: str
    what: str
    why: str | None
    confirm: str | None
    falsify: str | None
    eta: str | None


class PhaseTimelineEntryResponse(TypedDict):
    """Response body for one summarized phase-timeline interval."""

    phase: str
    start_t_s: float | None
    end_t_s: float | None
    speed_min_kmh: float | None
    speed_max_kmh: float | None
    has_fault_evidence: bool


class PhaseSegmentSummaryResponse(TypedDict):
    """Typed HTTP contract for a summarized driving-phase segment."""

    phase: str
    start_idx: int
    end_idx: int
    start_t_s: float | None
    end_t_s: float | None
    speed_min_kmh: float | None
    speed_max_kmh: float | None
    sample_count: int


class WholeRunContextIntervalResponse(TypedDict, total=False):
    """Persisted whole-run context segment keyed to the canonical window grid."""

    segment_index: Required[int]
    phase: Required[str]
    load_state: Required[str]
    start_window_index: Required[int]
    end_window_index: Required[int]
    start_t_s: float | None
    end_t_s: float | None
    speed_min_kmh: float | None
    speed_max_kmh: float | None
    speed_band: str | None
    full_context_window_count: Required[int]
    partial_context_window_count: Required[int]
    missing_context_window_count: Required[int]


class OrderTraceSupportIntervalResponse(TypedDict, total=False):
    """Compact persisted support interval derived from dense whole-run order traces."""

    interval_index: Required[int]
    start_window_index: Required[int]
    end_window_index: Required[int]
    matched_window_count: Required[int]
    support_ratio: Required[float]
    start_t_s: float | None
    end_t_s: float | None
    phase: str | None
    load_state: str | None
    speed_band: str | None
    mean_relative_error: float | None


class OrderTracePhaseSupportResponse(TypedDict, total=False):
    """Phase-aware support row for a compact whole-run order-trace summary."""

    phase: Required[str]
    eligible_window_count: Required[int]
    matched_window_count: Required[int]
    support_ratio: Required[float]


class OrderHarmonicEvidenceSummaryResponse(TypedDict, total=False):
    """Compact harmonic-specific evidence row for a whole-run order-trace summary."""

    harmonic: Required[int]
    order_label: Required[str]
    eligible_window_count: Required[int]
    matched_window_count: Required[int]
    support_ratio: Required[float]
    reference_coverage_ratio: Required[float]
    contiguous_support_ratio: Required[float]
    lock_score: Required[float]
    mean_relative_error: float | None
    relative_error_stddev: float | None
    drift_score: Required[float]
    peak_intensity_db: float | None
    mean_vibration_strength_db: float | None


class OrderTraceSummaryResponse(TypedDict, total=False):
    """Future persisted/report-facing summary shape for whole-run order traces."""

    hypothesis_key: Required[str]
    suspected_source: Required[str]
    order_family: Required[str]
    order_label: Required[str]
    total_window_count: Required[int]
    eligible_window_count: Required[int]
    matched_window_count: Required[int]
    support_ratio: Required[float]
    reference_coverage_ratio: Required[float]
    longest_contiguous_support_window_count: Required[int]
    contiguous_support_ratio: Required[float]
    support_intervals: Required[list[OrderTraceSupportIntervalResponse]]
    phase_support: Required[list[OrderTracePhaseSupportResponse]]
    harmonic_summaries: Required[list[OrderHarmonicEvidenceSummaryResponse]]
    stable_frequency_min_hz: float | None
    stable_frequency_max_hz: float | None
    exemplar_interval_index: int | None
    dominant_phase: str | None
    dominant_speed_band: str | None
    strongest_location: str | None
    mean_relative_error: float | None
    relative_error_stddev: float | None
    drift_score: Required[float]
    lock_score: Required[float]
    peak_intensity_db: float | None
    mean_vibration_strength_db: float | None
    ref_sources: Required[list[str]]


class SpatialLocationSummaryResponse(TypedDict, total=False):
    """Compact per-location support row for persisted spatial evidence."""

    location: Required[str]
    sensor_ids: Required[list[str]]
    supporting_window_count: Required[int]
    support_ratio: Required[float]
    coherent_window_count: Required[int]
    coherence_ratio: float | None
    peak_intensity_db: float | None
    mean_vibration_strength_db: float | None


class SpatialEvidenceSummaryResponse(TypedDict, total=False):
    """Future persisted/report-facing summary shape for whole-run spatial evidence."""

    candidate_key: Required[str]
    suspected_source: Required[str]
    proof_basis: Required[LocationProofBasis]
    total_window_count: Required[int]
    supporting_window_count: Required[int]
    supporting_sensor_count: Required[int]
    coherent_window_count: Required[int]
    coherence_ratio: float | None
    dominant_location: str | None
    runner_up_location: str | None
    location_separation_db: float | None
    dominance_ratio: float | None
    ambiguous_location: Required[bool]
    weak_spatial_separation: Required[bool]
    location_summaries: Required[list[SpatialLocationSummaryResponse]]


class DiagnosisExemplarReferenceResponse(TypedDict, total=False):
    """Compact reference to one persisted exemplar used by a fused diagnosis."""

    kind: Required[DiagnosisExemplarKind]
    order_hypothesis_key: str | None
    support_interval_index: int | None
    spatial_candidate_key: str | None
    context_segment_index: int | None
    location: str | None
    phase: str | None
    speed_band: str | None


class DiagnosisFactorDetailsResponse(TypedDict, total=False):
    """Structured details carried by one persisted diagnosis factor row."""

    raw_backed_sample_count: int | None
    supporting_window_count: int | None
    supporting_duration_s: float | None
    stable_frequency_min_hz: float | None
    stable_frequency_max_hz: float | None
    frequency_span_hz: float | None
    supporting_location_count: int | None
    top_support_location: str | None
    top_support_share: float | None
    mean_relative_error: float | None
    snr_db: float | None
    alternative_source: str | None
    speed_gap_window_count: int | None
    rpm_gap_window_count: int | None
    fallback_reason: str | None


class DiagnosisFactorResponse(TypedDict, total=False):
    """One stable support or counterevidence factor for a fused diagnosis."""

    factor_key: Required[DiagnosisFactorKey]
    polarity: Required[DiagnosisFactorPolarity]
    severity: Required[DiagnosisFactorSeverity]
    weight: Required[float]
    details: Required[DiagnosisFactorDetailsResponse]


class WholeRunDiagnosisSummaryResponse(TypedDict, total=False):
    """Future persisted/report-facing summary shape for fused whole-run diagnoses."""

    diagnosis_key: Required[str]
    suspected_source: Required[str]
    rank: Required[int]
    data_basis: Required[WholeRunDiagnosisDataBasis]
    support_score: float | None
    counterevidence_score: float | None
    total_score: float | None
    order_hypothesis_key: str | None
    spatial_candidate_key: str | None
    location_proof_basis: LocationProofBasis | None
    supporting_window_count: int | None
    supporting_duration_s: float | None
    supporting_sensor_count: int | None
    stable_frequency_min_hz: float | None
    stable_frequency_max_hz: float | None
    dominant_location: str | None
    runner_up_location: str | None
    dominant_phase: str | None
    dominant_speed_band: str | None
    location_separation_db: float | None
    dominance_ratio: float | None
    alternative_source: str | None
    confidence_gap_to_alternative: float | None
    ambiguous_diagnosis: Required[bool]
    ambiguous_location: Required[bool]
    suspicious: Required[bool]
    weak_spatial_separation: Required[bool]
    has_reference_gap: Required[bool]
    uses_summary_fallback: Required[bool]
    fallback_reason: str | None
    exemplar_references: Required[list[DiagnosisExemplarReferenceResponse]]
    support_factors: Required[list[DiagnosisFactorResponse]]
    counterevidence_factors: Required[list[DiagnosisFactorResponse]]


class SpeedStatsResponse(TypedDict):
    """Response body for one summarized speed-profile snapshot."""

    min_kmh: float | None
    max_kmh: float | None
    mean_kmh: float | None
    stddev_kmh: float | None
    range_kmh: float | None
    steady_speed: bool
    sample_count: int


class PhaseInfoResponse(TypedDict):
    """Response body for aggregate driving-phase coverage metrics."""

    phase_counts: dict[str, int]
    phase_pcts: dict[str, float]
    total_samples: int
    segment_count: int
    has_cruise: bool
    has_acceleration: bool
    cruise_pct: float
    idle_pct: float
    speed_unknown_pct: float


class StrengthBucketDistributionResponse(TypedDict):
    """Response body for per-location strength-bucket coverage."""

    total: int
    counts: dict[str, int]
    percent_time_l0: float
    percent_time_l1: float
    percent_time_l2: float
    percent_time_l3: float
    percent_time_l4: float
    percent_time_l5: float


class PhaseIntensityStatsResponse(TypedDict):
    """Response body for per-phase intensity aggregates at one location."""

    count: int
    mean_intensity_db: float | None
    max_intensity_db: float | None


class LocationIntensitySummaryResponse(TypedDict, total=False):
    """Response body for one sensor-location intensity summary row."""

    location: Required[str]
    partial_coverage: Required[bool]
    sample_count: Required[int]
    sample_coverage_ratio: Required[float]
    sample_coverage_warning: Required[bool]
    usable_sample_count: int | None
    usable_sample_coverage_ratio: float | None
    usable_sample_coverage_warning: bool | None
    mean_intensity_db: Required[float | None]
    p50_intensity_db: Required[float | None]
    p95_intensity_db: Required[float | None]
    max_intensity_db: Required[float | None]
    dropped_frames_delta: Required[float | None]
    queue_overflow_drops_delta: Required[float | None]
    strength_bucket_distribution: Required[StrengthBucketDistributionResponse]
    phase_intensity: dict[str, PhaseIntensityStatsResponse] | None


class SuspectedVibrationOriginPayload(TypedDict, total=False):
    """Typed HTTP contract for the serialized likely-origin payload."""

    location: str | None
    alternative_locations: list[str]
    suspected_source: str | None
    dominance_ratio: float | None
    weak_spatial_separation: bool | None
    speed_band: str | None
    dominant_phase: str | None
    explanation: PayloadValue


class AnalysisSummaryCoreResponse(TypedDict, total=False):
    """Canonical outward owner for summary core fields."""

    file_name: Required[str]
    run_id: Required[str]
    case_id: str | None
    rows: Required[int]
    duration_s: Required[float]
    record_length: Required[str]
    lang: Required[str]
    report_date: str | None
    start_time_utc: str | None
    end_time_utc: str | None
    sensor_model: str | None
    firmware_version: str | None
    raw_sample_rate_hz: Required[float | None]
    feature_interval_s: Required[float | None]
    fft_window_size_samples: int | None
    fft_window_type: str | None
    peak_picker_method: str | None
    accel_scale_g_per_lsb: Required[float | None]
    incomplete_for_order_analysis: Required[bool]
    metadata: Required[PayloadObject]
    speed_breakdown: Required[list[SpeedBreakdownRow]]
    phase_speed_breakdown: Required[list[PhaseSpeedBreakdownRow]]
    phase_segments: Required[list[PhaseSegmentSummaryResponse]]
    run_noise_baseline_db: Required[float | None]
    speed_breakdown_skipped_reason: Required[PayloadObject | None]
    findings: Required[list[FindingPayload]]
    top_causes: Required[list[FindingPayload]]
    most_likely_origin: Required[SuspectedVibrationOriginPayload]
    test_plan: Required[list[TestPlanStepResponse]]
    phase_timeline: Required[list[PhaseTimelineEntryResponse]]
    whole_run_context_intervals: list[WholeRunContextIntervalResponse]
    whole_run_order_summaries: list[OrderTraceSummaryResponse]
    whole_run_spatial_summaries: list[SpatialEvidenceSummaryResponse]
    whole_run_diagnosis_summaries: list[WholeRunDiagnosisSummaryResponse]
    speed_stats: Required[SpeedStatsResponse]
    speed_stats_by_phase: Required[dict[str, SpeedStatsResponse]]
    phase_info: Required[PhaseInfoResponse]
    sensor_locations: Required[list[str]]
    sensor_locations_connected_throughout: Required[list[str]]
    sensor_count_used: Required[int]
    sensor_intensity_by_location: Required[list[LocationIntensitySummaryResponse]]
    run_suitability: Required[list[RunSuitabilityCheck]]
    data_quality: Required[DataQualityResponse]
    samples: list[PayloadObject]
    plots: PlotDataResult | None
    analysis_metadata: PayloadObject


class AnalysisSummaryResponse(AnalysisSummaryCoreResponse):
    """Canonical shared owner for the persisted analysis summary wrapper."""

    warnings: Required[list[SummaryWarningResponse]]


# Plain assignment (not ``type`` statement) so ``AnalysisSummary is
# AnalysisSummaryResponse`` stays True at runtime — the hygiene parity
# suite relies on this identity.
AnalysisSummary = AnalysisSummaryResponse


def _configure_pydantic_schema(typed_dict: Any, config: ConfigDict) -> None:
    typed_dict.__pydantic_config__ = config


for _typed_dict in (
    SummaryWarningResponse,
    TestPlanStepResponse,
    PhaseTimelineEntryResponse,
    PhaseSegmentSummaryResponse,
    WholeRunContextIntervalResponse,
    OrderTraceSupportIntervalResponse,
    OrderTracePhaseSupportResponse,
    OrderHarmonicEvidenceSummaryResponse,
    OrderTraceSummaryResponse,
    SpatialLocationSummaryResponse,
    SpatialEvidenceSummaryResponse,
    DiagnosisExemplarReferenceResponse,
    DiagnosisFactorDetailsResponse,
    DiagnosisFactorResponse,
    WholeRunDiagnosisSummaryResponse,
    SpeedStatsResponse,
    PhaseInfoResponse,
    OutlierSummaryResponse,
    DataQualityRequiredMissingPctResponse,
    DataQualitySpeedCoverageResponse,
    DataQualityAccelSanityResponse,
    DataQualityOutliersResponse,
    DataQualityResponse,
    StrengthBucketDistributionResponse,
    PhaseIntensityStatsResponse,
    LocationIntensitySummaryResponse,
):
    _configure_pydantic_schema(_typed_dict, _IGNORE_EXTRA_TYPEDDICT_CONFIG)


for _strict_typed_dict in (
    AmplitudeMetric,
    RunSuitabilityCheck,
    FindingPayload,
    SuspectedVibrationOriginPayload,
    AnalysisSummaryCoreResponse,
    AnalysisSummaryResponse,
):
    _configure_pydantic_schema(_strict_typed_dict, _FORBID_EXTRA_TYPEDDICT_CONFIG)
