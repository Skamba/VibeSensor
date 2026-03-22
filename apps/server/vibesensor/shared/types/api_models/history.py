"""History and finding-oriented HTTP API models.

Stable exact analysis/history view shapes live in
``vibesensor.shared.types.analysis_views`` so the HTTP and boundary layers do
not maintain duplicate owners for the same schema concepts.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from vibesensor.shared.types.analysis_views import (
    AmpVsPhaseRow,
    FindingEvidenceMetrics,
    FreqVsSpeedByFindingSeries,
    LocationHotspotPayload,
    MatchedAmpVsSpeedSeries,
    MatchedPoint,
    PeakTableRow,
    PhaseBoundary,
    PhaseEvidence,
    PhaseSegmentOut,
    PhaseSpeedBreakdownRow,
    PlotDataResult,
    SpectrogramResult,
    SpeedBreakdownRow,
)

from .base import ApiPayloadObject, ApiPayloadValue, _StrictBase

__all__ = [
    "AmpVsPhaseRow",
    "FindingEvidenceMetrics",
    "FreqVsSpeedByFindingSeries",
    "LocationHotspotPayload",
    "MatchedAmpVsSpeedSeries",
    "MatchedPoint",
    "PeakTableRow",
    "PhaseBoundary",
    "PhaseEvidence",
    "PhaseSegmentOut",
    "PhaseSpeedBreakdownRow",
    "PlotDataResult",
    "SpectrogramResult",
    "SpeedBreakdownRow",
]


class HistoryListEntryResponse(BaseModel):
    """Response body for a single history-run list row."""

    run_id: str
    status: str
    start_time_utc: str
    end_time_utc: str | None = None
    created_at: str
    sample_count: int
    error_message: str | None = None


class HistoryListResponse(BaseModel):
    """Response body listing recorded run summaries."""

    runs: list[HistoryListEntryResponse]


class HistoryRunResponse(_StrictBase):
    """Response body for a single history run with metadata and optional analysis."""

    run_id: str
    status: str
    metadata: ApiPayloadObject = Field(default_factory=dict)
    analysis: AnalysisSummaryResponse | None = None


class HistoryInsightWarningResponse(BaseModel):
    """Response body for a localized history/run trust warning."""

    code: str
    severity: Literal["warn", "error"]
    applies_to: str
    title: str
    detail: str | None = None


class SummaryWarningResponse(BaseModel):
    """Response body for a persisted summary warning before localization."""

    code: str
    severity: Literal["warn", "error"]
    applies_to: str
    title: ApiPayloadValue
    detail: ApiPayloadValue = None


class TestPlanStepResponse(BaseModel):
    """Response body for one recommended next-step action."""

    action_id: str
    what: str
    why: str | None
    confirm: str | None
    falsify: str | None
    eta: str | None


class PhaseTimelineEntryResponse(BaseModel):
    """Response body for one summarized phase-timeline interval."""

    phase: str
    start_t_s: float | None
    end_t_s: float | None
    speed_min_kmh: float | None
    speed_max_kmh: float | None
    has_fault_evidence: bool


class SpeedStatsResponse(BaseModel):
    """Response body for one summarized speed-profile snapshot."""

    min_kmh: float | None
    max_kmh: float | None
    mean_kmh: float | None
    stddev_kmh: float | None
    range_kmh: float | None
    steady_speed: bool
    sample_count: int


class PhaseInfoResponse(BaseModel):
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


class OutlierSummaryResponse(BaseModel):
    """Response body for an outlier-summary bucket."""

    count: int
    outlier_count: int
    outlier_pct: float
    lower_bound: float | None
    upper_bound: float | None


class DataQualityRequiredMissingPctResponse(BaseModel):
    """Response body for required-field missing percentages."""

    t_s: float
    speed_kmh: float
    accel_x: float
    accel_y: float
    accel_z: float


class DataQualitySpeedCoverageResponse(BaseModel):
    """Response body for summarized speed-coverage statistics."""

    non_null_pct: float
    min_kmh: float | None
    max_kmh: float | None
    mean_kmh: float | None
    stddev_kmh: float | None
    count_non_null: int


class DataQualityAccelSanityResponse(BaseModel):
    """Response body for acceleration sanity diagnostics."""

    x_mean: float | None
    x_variance: float | None
    y_mean: float | None
    y_variance: float | None
    z_mean: float | None
    z_variance: float | None
    sensor_limit: float | None
    saturation_count: int | None


class DataQualityOutliersResponse(BaseModel):
    """Response body for grouped outlier summaries."""

    accel_magnitude: OutlierSummaryResponse
    amplitude_metric: OutlierSummaryResponse


class DataQualityResponse(BaseModel):
    """Response body for run-level data-quality diagnostics."""

    required_missing_pct: DataQualityRequiredMissingPctResponse
    speed_coverage: DataQualitySpeedCoverageResponse
    accel_sanity: DataQualityAccelSanityResponse
    outliers: DataQualityOutliersResponse


class StrengthBucketDistributionResponse(BaseModel):
    """Response body for per-location strength-bucket coverage."""

    total: int
    counts: dict[str, int]
    percent_time_l0: float
    percent_time_l1: float
    percent_time_l2: float
    percent_time_l3: float
    percent_time_l4: float
    percent_time_l5: float


class PhaseIntensityStatsResponse(BaseModel):
    """Response body for per-phase intensity aggregates at one location."""

    count: int
    mean_intensity_db: float | None
    max_intensity_db: float | None


class LocationIntensitySummaryResponse(BaseModel):
    """Response body for one sensor-location intensity summary row."""

    location: str
    partial_coverage: bool
    sample_count: int
    sample_coverage_ratio: float
    sample_coverage_warning: bool
    mean_intensity_db: float | None
    p50_intensity_db: float | None
    p95_intensity_db: float | None
    max_intensity_db: float | None
    dropped_frames_delta: float | None
    queue_overflow_drops_delta: float | None
    strength_bucket_distribution: StrengthBucketDistributionResponse
    phase_intensity: dict[str, PhaseIntensityStatsResponse] | None = None


class AmplitudeMetric(_StrictBase):
    """HTTP contract for finding amplitude/strength metadata."""

    name: str | None = None
    value: float | None = None
    units: str | None = None
    definition: ApiPayloadValue = None


class FindingPayload(_StrictBase):
    """HTTP contract for one serialized finding in analysis history payloads.

    This schema mirrors ``shared.boundaries.analysis_payload.FindingPayload``.
    It intentionally includes a few presentation-oriented projections
    (``evidence_summary``, ``frequency_hz_or_order``, ``amplitude_metric``,
    and the confidence label fields) alongside the domain-owned finding data.
    """

    finding_id: str
    finding_key: str | None = None
    suspected_source: str
    evidence_summary: ApiPayloadValue
    frequency_hz_or_order: ApiPayloadValue
    amplitude_metric: AmplitudeMetric
    confidence: float | None
    finding_kind: str | None = None
    severity: str | None = None
    confidence_label_key: str | None = None
    confidence_tone: str | None = None
    confidence_pct: str | None = None
    matched_points: list[MatchedPoint] = Field(default_factory=list)
    location_hotspot: LocationHotspotPayload | None = None
    strongest_location: str | None = None
    strongest_speed_band: str | None = None
    dominant_phase: str | None = None
    dominance_ratio: float | None = None
    weak_spatial_separation: bool | None = None
    diffuse_excitation: bool | None = None
    phase_evidence: PhaseEvidence | None = None
    evidence_metrics: FindingEvidenceMetrics | None = None
    ranking_score: float | None = None
    peak_classification: str | None = None
    signatures_observed: list[str] = Field(default_factory=list)
    order: str | None = None


class RunSuitabilityCheck(_StrictBase):
    """Typed HTTP contract for one run-suitability diagnostic check."""

    check: str
    check_key: str
    state: str
    explanation: ApiPayloadValue = None


class PhaseSegmentSummaryResponse(BaseModel):
    """Typed HTTP contract for a summarized driving-phase segment."""

    phase: str
    start_idx: int
    end_idx: int
    start_t_s: float | None
    end_t_s: float | None
    speed_min_kmh: float | None
    speed_max_kmh: float | None
    sample_count: int


class SuspectedVibrationOriginPayload(_StrictBase):
    """Typed HTTP contract for the serialized likely-origin payload."""

    location: str | None = None
    alternative_locations: list[str] = Field(default_factory=list)
    suspected_source: str | None = None
    dominance_ratio: float | None = None
    weak_spatial_separation: bool | None = None
    speed_band: str | None = None
    dominant_phase: str | None = None
    explanation: ApiPayloadValue = None


class _AnalysisSummaryCoreResponse(_StrictBase):
    """Shared typed HTTP contract fields used by history-run analysis payloads."""

    file_name: str
    run_id: str
    rows: int
    duration_s: float
    record_length: str
    lang: str
    report_date: str | None = None
    start_time_utc: str | None = None
    end_time_utc: str | None = None
    sensor_model: str | None = None
    firmware_version: str | None = None
    raw_sample_rate_hz: float | None
    feature_interval_s: float | None
    fft_window_size_samples: int | None = None
    fft_window_type: str | None = None
    peak_picker_method: str | None = None
    accel_scale_g_per_lsb: float | None
    incomplete_for_order_analysis: bool
    metadata: ApiPayloadObject
    speed_breakdown: list[SpeedBreakdownRow]
    phase_speed_breakdown: list[PhaseSpeedBreakdownRow]
    phase_segments: list[PhaseSegmentSummaryResponse]
    run_noise_baseline_db: float | None
    speed_breakdown_skipped_reason: ApiPayloadObject | None
    findings: list[FindingPayload]
    top_causes: list[FindingPayload]
    most_likely_origin: SuspectedVibrationOriginPayload
    test_plan: list[TestPlanStepResponse]
    phase_timeline: list[PhaseTimelineEntryResponse]
    speed_stats: SpeedStatsResponse
    speed_stats_by_phase: dict[str, SpeedStatsResponse]
    phase_info: PhaseInfoResponse
    sensor_locations: list[str]
    sensor_locations_connected_throughout: list[str]
    sensor_count_used: int
    sensor_intensity_by_location: list[LocationIntensitySummaryResponse]
    run_suitability: list[RunSuitabilityCheck]
    data_quality: DataQualityResponse
    samples: list[ApiPayloadObject] = Field(default_factory=list)
    plots: PlotDataResult | None = None
    analysis_metadata: ApiPayloadObject = Field(default_factory=dict)


class AnalysisSummaryResponse(_AnalysisSummaryCoreResponse):
    """Typed HTTP contract for the persisted analysis summary on one history run."""

    warnings: list[SummaryWarningResponse]


class HistoryInsightsAnalyzingResponse(BaseModel):
    """Response body for a history run whose analysis is still in progress."""

    run_id: str
    status: Literal["analyzing"]


class HistoryInsightsResponse(_AnalysisSummaryCoreResponse):
    """Response body for the localized history insights endpoint payload."""

    status: Literal["complete"] = "complete"
    warnings: list[HistoryInsightWarningResponse] = Field(default_factory=list)


class DeleteHistoryRunResponse(BaseModel):
    """Response body confirming deletion of a history run."""

    run_id: str
    status: str
