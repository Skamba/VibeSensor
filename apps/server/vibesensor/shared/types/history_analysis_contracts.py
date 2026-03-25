"""Shared analysis/history wrapper contracts reused by boundary and HTTP layers.

These TypedDicts are the single semantic owners for analysis/history wrapper
and composite contracts that are shared between persisted boundary payloads and
the HTTP/OpenAPI response schema. ``FindingPayload`` is canonically owned here.
Boundary modules only alias contracts that need boundary-specific payload
names, while endpoint-specific HTTP wrappers remain local to
``shared.types.api_models.history``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, Required, TypeAlias, cast

from pydantic import ConfigDict
from typing_extensions import TypedDict

from vibesensor.shared.types.analysis_views import (
    FindingEvidenceMetrics,
    LocationHotspotPayload,
    MatchedPoint,
    PhaseEvidence,
    PhaseSpeedBreakdownRow,
    PlotDataResult,
    SpeedBreakdownRow,
)
from vibesensor.shared.types.json_types import (
    JsonObject,
    JsonSchemaObject,
    JsonSchemaValue,
    JsonValue,
)

__all__ = [
    "AmplitudeMetric",
    "AnalysisSummaryCoreResponse",
    "AnalysisSummaryResponse",
    "DataQualityAccelSanityResponse",
    "DataQualityOutliersResponse",
    "DataQualityRequiredMissingPctResponse",
    "DataQualityResponse",
    "DataQualitySpeedCoverageResponse",
    "FindingPayload",
    "LocationIntensitySummaryResponse",
    "OutlierSummaryResponse",
    "PayloadObject",
    "PayloadValue",
    "payload_object_from_json",
    "payload_objects_from_json",
    "payload_value_from_json",
    "PhaseInfoResponse",
    "PhaseIntensityStatsResponse",
    "PhaseSegmentSummaryResponse",
    "PhaseTimelineEntryResponse",
    "RunSuitabilityCheck",
    "SpeedStatsResponse",
    "StrengthBucketDistributionResponse",
    "SummaryWarningResponse",
    "SuspectedVibrationOriginPayload",
    "TestPlanStepResponse",
]

PayloadObject: TypeAlias = JsonSchemaObject
PayloadValue: TypeAlias = JsonSchemaValue


def payload_value_from_json(value: JsonValue | None) -> PayloadValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        # History/report payload producers only emit the bounded JSON depth
        # modeled by ``PayloadValue``, but mypy cannot prove that through the
        # recursive conversion helper.
        return cast(PayloadValue, [payload_value_from_json(item) for item in value])
    return cast(PayloadValue, payload_object_from_json(value))


def payload_object_from_json(value: JsonObject) -> PayloadObject:
    return cast(PayloadObject, {key: payload_value_from_json(item) for key, item in value.items()})


def payload_objects_from_json(values: Sequence[JsonObject]) -> list[PayloadObject]:
    return [payload_object_from_json(value) for value in values]


_FORBID_EXTRA_TYPEDDICT_CONFIG = ConfigDict(extra="forbid")
_IGNORE_EXTRA_TYPEDDICT_CONFIG = ConfigDict(extra="ignore")


class AmplitudeMetric(TypedDict, total=False):
    """HTTP contract for finding amplitude/strength metadata."""

    name: str | None
    value: float | None
    units: str | None
    definition: PayloadValue


class RunSuitabilityCheck(TypedDict, total=False):
    """Typed HTTP contract for one run-suitability diagnostic check."""

    check: Required[str]
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


class OutlierSummaryResponse(TypedDict):
    """Response body for an outlier-summary bucket."""

    count: int
    outlier_count: int
    outlier_pct: float
    lower_bound: float | None
    upper_bound: float | None


class DataQualityRequiredMissingPctResponse(TypedDict):
    """Response body for required-field missing percentages."""

    t_s: float
    speed_kmh: float
    accel_x: float
    accel_y: float
    accel_z: float


class DataQualitySpeedCoverageResponse(TypedDict):
    """Response body for summarized speed-coverage statistics."""

    non_null_pct: float
    min_kmh: float | None
    max_kmh: float | None
    mean_kmh: float | None
    stddev_kmh: float | None
    count_non_null: int


class DataQualityAccelSanityResponse(TypedDict):
    """Response body for acceleration sanity diagnostics."""

    x_mean: float | None
    x_variance: float | None
    y_mean: float | None
    y_variance: float | None
    z_mean: float | None
    z_variance: float | None
    sensor_limit: float | None
    saturation_count: int | None


class DataQualityOutliersResponse(TypedDict):
    """Response body for grouped outlier summaries."""

    accel_magnitude: OutlierSummaryResponse
    amplitude_metric: OutlierSummaryResponse


class DataQualityResponse(TypedDict):
    """Response body for run-level data-quality diagnostics."""

    required_missing_pct: DataQualityRequiredMissingPctResponse
    speed_coverage: DataQualitySpeedCoverageResponse
    accel_sanity: DataQualityAccelSanityResponse
    outliers: DataQualityOutliersResponse


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
    mean_intensity_db: Required[float | None]
    p50_intensity_db: Required[float | None]
    p95_intensity_db: Required[float | None]
    max_intensity_db: Required[float | None]
    dropped_frames_delta: Required[float | None]
    queue_overflow_drops_delta: Required[float | None]
    strength_bucket_distribution: Required[StrengthBucketDistributionResponse]
    phase_intensity: dict[str, PhaseIntensityStatsResponse] | None


class FindingPayload(TypedDict, total=False):
    """Canonical shared contract for one serialized finding payload.

    Boundary serializers and HTTP models should import this TypedDict directly
    so future field changes have one source of truth. It intentionally includes
    a few presentation-oriented projections (``evidence_summary``,
    ``frequency_hz_or_order``, ``amplitude_metric``, and the confidence label
    fields) alongside the domain-owned finding data.
    """

    finding_id: Required[str]
    finding_key: str | None
    suspected_source: Required[str]
    evidence_summary: Required[str]
    frequency_hz_or_order: Required[float | str]
    amplitude_metric: Required[AmplitudeMetric]
    confidence: Required[float | None]
    finding_kind: str | None
    severity: str | None
    confidence_label_key: str | None
    confidence_tone: str | None
    confidence_pct: str | None
    matched_points: list[MatchedPoint]
    location_hotspot: LocationHotspotPayload | None
    strongest_location: str | None
    strongest_speed_band: str | None
    dominant_phase: str | None
    dominance_ratio: float | None
    weak_spatial_separation: bool | None
    diffuse_excitation: bool | None
    phase_evidence: PhaseEvidence | None
    evidence_metrics: FindingEvidenceMetrics | None
    ranking_score: float | None
    peak_classification: str | None
    signatures_observed: list[str]
    order: str | None


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
    """Shared core fields reused by persisted and localized history summaries."""

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
    """Typed HTTP contract for the persisted analysis summary on one history run."""

    warnings: Required[list[SummaryWarningResponse]]


def _configure_pydantic_schema(typed_dict: Any, config: ConfigDict) -> None:
    typed_dict.__pydantic_config__ = config


for _typed_dict in (
    SummaryWarningResponse,
    TestPlanStepResponse,
    PhaseTimelineEntryResponse,
    PhaseSegmentSummaryResponse,
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
