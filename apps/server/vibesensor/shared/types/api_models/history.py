"""History and finding-oriented HTTP API models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema

from .base import ApiPayloadObject, ApiPayloadValue, _ExtraAllowBase


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


class HistoryRunResponse(_ExtraAllowBase):
    """Response body for a single history run with metadata and optional analysis."""

    run_id: str
    status: str
    metadata: ApiPayloadObject = Field(default_factory=dict)
    analysis: AnalysisSummaryResponse | SkipJsonSchema[ApiPayloadObject] | None = None


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


class MatchedPoint(_ExtraAllowBase):
    """HTTP contract for one serialized finding matched-point observation."""

    t_s: float | None = None
    speed_kmh: float | None = None
    predicted_hz: float | None = None
    matched_hz: float | None = None
    rel_error: float | None = None
    amp: float | None = None
    location: str | None = None
    phase: str | None = None


class PhaseEvidence(_ExtraAllowBase):
    """HTTP contract for optional driving-phase evidence attached to a finding."""

    cruise_fraction: float | None = None
    phases_detected: list[str] = Field(default_factory=list)


class AmplitudeMetric(_ExtraAllowBase):
    """HTTP contract for finding amplitude/strength metadata."""

    name: str | None = None
    value: float | None = None
    units: str | None = None
    definition: ApiPayloadValue = None


class LocationHotspotPayload(_ExtraAllowBase):
    """HTTP contract for serialized location-hotspot evidence."""

    dominance_ratio: float | None = None
    location_count: int | None = None
    top_location: str | None = None
    second_location: str | None = None
    ambiguous_location: bool | None = None
    ambiguous_locations: list[str] = Field(default_factory=list)
    localization_confidence: float | None = None
    weak_spatial_separation: bool | None = None


class FindingEvidenceMetrics(_ExtraAllowBase):
    """HTTP contract for serialized evidence metrics attached to a finding."""

    match_rate: float | None = None
    global_match_rate: float | None = None
    focused_speed_band: str | None = None
    mean_relative_error: float | None = None
    mean_noise_floor_db: float | None = None
    vibration_strength_db: float | None = None
    possible_samples: int | None = None
    matched_samples: int | None = None
    frequency_correlation: float | None = None
    per_phase_confidence: dict[str, float] | None = None
    phases_with_evidence: int | None = None
    presence_ratio: float | None = None
    median_intensity_db: float | None = None
    p95_intensity_db: float | None = None
    max_intensity_db: float | None = None
    burstiness: float | None = None
    run_noise_baseline_db: float | None = None
    median_relative_to_run_noise: float | None = None
    p95_relative_to_run_noise: float | None = None
    sample_count: int | None = None
    total_samples: int | None = None
    spatial_concentration: float | None = None
    spatial_uniformity: float | None = None
    speed_uniformity: float | None = None


class FindingPayload(_ExtraAllowBase):
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


class SpeedBreakdownRow(BaseModel):
    """Typed HTTP contract for one speed-band aggregate row."""

    speed_range: str
    count: int
    mean_vibration_strength_db: float | None
    max_vibration_strength_db: float | None


class PhaseSpeedBreakdownRow(BaseModel):
    """Typed HTTP contract for one phase-aware speed aggregate row."""

    phase: str
    count: int
    mean_speed_kmh: float | None
    max_speed_kmh: float | None
    mean_vibration_strength_db: float | None
    max_vibration_strength_db: float | None


class RunSuitabilityCheck(_ExtraAllowBase):
    """Typed HTTP contract for one run-suitability diagnostic check."""

    check: str
    check_key: str
    state: str
    explanation: ApiPayloadValue = None


class PeakTableRow(_ExtraAllowBase):
    """Typed HTTP contract for one ranked peak table row."""

    rank: int
    frequency_hz: float
    order_label: str
    max_intensity_db: float | None
    median_intensity_db: float | None
    p95_intensity_db: float | None
    run_noise_baseline_db: float | None
    median_vs_run_noise_ratio: float
    p95_vs_run_noise_ratio: float
    strength_floor_db: float | None
    strength_db: float | None
    presence_ratio: float
    burstiness: float
    persistence_score: float
    suspected_source: str
    peak_classification: str
    typical_speed_band: str


class MatchedAmpVsSpeedSeries(BaseModel):
    """Typed HTTP contract for one finding's amp-vs-speed series."""

    label: str
    points: list[tuple[float, float]]


class FreqVsSpeedByFindingSeries(BaseModel):
    """Typed HTTP contract for one finding's freq-vs-speed series."""

    label: str
    matched: list[tuple[float, float]]
    predicted: list[tuple[float, float]]


class AmpVsPhaseRow(BaseModel):
    """Typed HTTP contract for one phase-grouped vibration aggregate row."""

    phase: str
    count: int
    mean_vib_db: float
    max_vib_db: float | None
    mean_speed_kmh: float | None


class PhaseSegmentOut(BaseModel):
    """Typed HTTP contract for a serialized driving-phase segment."""

    phase: str
    start_t_s: float | None
    end_t_s: float | None


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


class PhaseBoundary(BaseModel):
    """Typed HTTP contract for a phase-boundary marker."""

    phase: str
    t_s: float | None
    end_t_s: float | None


class SpectrogramResult(_ExtraAllowBase):
    """Typed HTTP contract for a serialized spectrogram grid."""

    x_axis: str
    x_label_key: str
    x_bins: list[float]
    y_bins: list[float]
    cells: list[list[float]]
    max_amp: float
    x_bin_width: float | None = None
    y_bin_width: float | None = None


class PlotDataResult(_ExtraAllowBase):
    """Typed HTTP contract for serialized plot data attached to a run summary."""

    vib_magnitude: list[tuple[float, float, str]]
    dominant_freq: list[tuple[float, float]]
    amp_vs_speed: list[tuple[float, float]]
    amp_vs_phase: list[AmpVsPhaseRow]
    matched_amp_vs_speed: list[MatchedAmpVsSpeedSeries]
    freq_vs_speed_by_finding: list[FreqVsSpeedByFindingSeries]
    steady_speed_distribution: dict[str, float] | None
    fft_spectrum: list[tuple[float, float]]
    fft_spectrum_raw: list[tuple[float, float]]
    peaks_spectrogram: SpectrogramResult
    peaks_spectrogram_raw: SpectrogramResult
    peaks_table: list[PeakTableRow]
    phase_segments: list[PhaseSegmentOut]
    phase_boundaries: list[PhaseBoundary]


class SuspectedVibrationOriginPayload(_ExtraAllowBase):
    """Typed HTTP contract for the serialized likely-origin payload."""

    location: str | None = None
    alternative_locations: list[str] = Field(default_factory=list)
    suspected_source: str | None = None
    dominance_ratio: float | None = None
    weak_spatial_separation: bool | None = None
    speed_band: str | None = None
    dominant_phase: str | None = None
    explanation: ApiPayloadValue = None


class _AnalysisSummaryCoreResponse(_ExtraAllowBase):
    """Shared typed HTTP contract fields used by history-run analysis payloads."""

    file_name: str
    run_id: str
    rows: int
    duration_s: float
    record_length: str
    lang: str
    report_date: ApiPayloadValue = None
    start_time_utc: ApiPayloadValue = None
    end_time_utc: ApiPayloadValue = None
    sensor_model: ApiPayloadValue = None
    firmware_version: ApiPayloadValue = None
    raw_sample_rate_hz: float | None
    feature_interval_s: float | None
    fft_window_size_samples: ApiPayloadValue = None
    fft_window_type: ApiPayloadValue = None
    peak_picker_method: ApiPayloadValue = None
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


class HistoryInsightsResponse(_AnalysisSummaryCoreResponse):
    """Response body for the localized history insights endpoint payload."""

    status: str | None = None
    warnings: list[HistoryInsightWarningResponse] = Field(default_factory=list)


class DeleteHistoryRunResponse(BaseModel):
    """Response body confirming deletion of a history run."""

    run_id: str
    status: str
