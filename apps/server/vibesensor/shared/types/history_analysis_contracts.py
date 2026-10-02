"""Shared analysis-summary contract: the persisted summary JSON and its HTTP schema.

``AnalysisSummary`` is the one definition of the persisted analysis summary
(``runs.analysis_json``) and of the ``HistoryRunResponse.analysis`` OpenAPI
schema. Its whole-run rows reuse the frozen dataclass contracts (``JsonContract``)
that the post-analysis pipeline produces, so each row shape is defined once.
``FindingPayload`` lives in ``finding_payload_parts``; endpoint-specific HTTP
wrappers stay in ``adapters.http.models.history``.
"""

from __future__ import annotations

from typing import Annotated, Literal, Required, TypedDict

from pydantic import ConfigDict, with_config

from vibesensor.shared.types.analysis_views import (
    PhaseSpeedBreakdownRow,
    PlotDataResult,
    SpeedBreakdownRow,
)
from vibesensor.shared.types.data_quality_contracts import DataQualityResponse
from vibesensor.shared.types.finding_payload_parts import FindingPayload
from vibesensor.shared.types.json_contract import AsJsonObject
from vibesensor.shared.types.json_types import JsonSchemaObject, JsonSchemaValue
from vibesensor.shared.types.order_trace_contracts import OrderTraceSummary
from vibesensor.shared.types.spatial_evidence_contracts import SpatialEvidenceSummary
from vibesensor.shared.types.whole_run_analysis import WholeRunContextInterval
from vibesensor.shared.types.whole_run_diagnosis_contracts import WholeRunDiagnosisSummary

__all__ = [
    "AnalysisSummary",
    "AnalysisSummaryCoreResponse",
    "LocationIntensitySummaryResponse",
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
    "TestPlanStepResponse",
]

_FORBID_EXTRA = ConfigDict(extra="forbid")
# Nested rows ignore unknown keys so older persisted summaries keep validating;
# without their own config they would inherit the parent's ``forbid``.
_IGNORE_EXTRA = ConfigDict(extra="ignore")

type PayloadObject = JsonSchemaObject
type PayloadValue = JsonSchemaValue


@with_config(_FORBID_EXTRA)
class RunSuitabilityCheck(TypedDict, total=False):
    """Typed HTTP contract for one run-suitability diagnostic check."""

    check_key: Required[str]
    state: Required[str]
    explanation: PayloadValue


@with_config(_IGNORE_EXTRA)
class SummaryWarningResponse(TypedDict, total=False):
    """Response body for a persisted summary warning before localization."""

    code: Required[str]
    severity: Required[Literal["warn", "error"]]
    applies_to: Required[str]
    title: Required[PayloadValue]
    detail: PayloadValue


@with_config(_IGNORE_EXTRA)
class TestPlanStepResponse(TypedDict):
    """Response body for one recommended next-step action."""

    action_id: str
    what: str
    why: str | None
    confirm: str | None
    falsify: str | None
    eta: str | None


@with_config(_IGNORE_EXTRA)
class PhaseTimelineEntryResponse(TypedDict):
    """Response body for one summarized phase-timeline interval."""

    phase: str
    start_t_s: float | None
    end_t_s: float | None
    speed_min_kmh: float | None
    speed_max_kmh: float | None
    has_fault_evidence: bool


@with_config(_IGNORE_EXTRA)
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


@with_config(_IGNORE_EXTRA)
class SpeedStatsResponse(TypedDict):
    """Response body for one summarized speed-profile snapshot."""

    min_kmh: float | None
    max_kmh: float | None
    mean_kmh: float | None
    stddev_kmh: float | None
    range_kmh: float | None
    steady_speed: bool
    sample_count: int


@with_config(_IGNORE_EXTRA)
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


@with_config(_IGNORE_EXTRA)
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


@with_config(_IGNORE_EXTRA)
class PhaseIntensityStatsResponse(TypedDict):
    """Response body for per-phase intensity aggregates at one location."""

    count: int
    mean_intensity_db: float | None
    max_intensity_db: float | None


@with_config(_IGNORE_EXTRA)
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


@with_config(_FORBID_EXTRA)
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


@with_config(_FORBID_EXTRA)
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
    whole_run_context_intervals: list[Annotated[WholeRunContextInterval, AsJsonObject]]
    whole_run_order_summaries: list[Annotated[OrderTraceSummary, AsJsonObject]]
    whole_run_spatial_summaries: list[Annotated[SpatialEvidenceSummary, AsJsonObject]]
    whole_run_diagnosis_summaries: list[Annotated[WholeRunDiagnosisSummary, AsJsonObject]]
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


@with_config(_FORBID_EXTRA)
class AnalysisSummary(AnalysisSummaryCoreResponse):
    """Persisted analysis summary (``runs.analysis_json``) and its HTTP response schema."""

    warnings: Required[list[SummaryWarningResponse]]
