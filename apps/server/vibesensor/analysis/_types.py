"""Shared lightweight typing aliases for the analysis package."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Protocol, TypeAlias, TypedDict, TypeGuard

from ..json_types import JsonObject, JsonValue
from ..json_types import is_json_object as is_json_object  # re-export canonical source
from .phase_segmentation import DrivingPhase

if TYPE_CHECKING:
    from .plot_data import PlotDataResult

Sample: TypeAlias = JsonObject
"""A single recorded sample row.  Alias for ``JsonObject``; used for
semantic clarity across analysis modules, not additional type safety."""

MetadataDict: TypeAlias = JsonObject
"""Run metadata dict.  Alias for ``JsonObject``; carries run-level
configuration, firmware info, and timing details."""

IntensityRow: TypeAlias = JsonObject
"""Per-location intensity breakdown row."""

I18nRef: TypeAlias = JsonObject
"""Internationalised text reference (key + optional interpolation vars)."""

TestStep: TypeAlias = JsonObject
"""A single diagnostic test-plan step."""


class AmplitudeMetric(TypedDict):
    name: str
    value: float | None
    units: str
    definition: JsonValue


class PhaseEvidence(TypedDict, total=False):
    cruise_fraction: float
    phases_detected: list[str]


class MatchedPoint(TypedDict, total=False):
    t_s: float | None
    speed_kmh: float | None
    predicted_hz: float
    matched_hz: float
    rel_error: float
    amp: float
    location: str
    phase: str | None


class LocationHotspot(TypedDict, total=False):
    speed_range: str
    location: str
    mean_amp: float
    dominance_ratio: float | None
    location_count: int
    top_location: str
    second_location: str | None
    top_location_samples: int
    second_location_samples: int
    corroborated_by_n_sensors: int
    total_samples: int
    ambiguous_location: bool
    ambiguous_locations: list[str]
    partial_coverage: bool
    localization_confidence: float
    weak_spatial_separation: bool
    no_wheel_sensors: bool
    per_bin_results: list[LocationHotspot]


class FindingEvidenceMetrics(TypedDict, total=False):
    match_rate: float
    global_match_rate: float
    focused_speed_band: str | None
    mean_relative_error: float
    mean_noise_floor_db: float
    vibration_strength_db: float
    possible_samples: int
    matched_samples: int
    frequency_correlation: float | None
    per_phase_confidence: dict[str, float] | None
    phases_with_evidence: int
    presence_ratio: float
    median_intensity_db: float
    p95_intensity_db: float
    max_intensity_db: float
    burstiness: float
    run_noise_baseline_db: float | None
    median_relative_to_run_noise: float
    p95_relative_to_run_noise: float
    sample_count: int
    total_samples: int
    spatial_concentration: float
    spatial_uniformity: float | None
    speed_uniformity: float | None


class FindingRequired(TypedDict):
    finding_id: str
    suspected_source: str
    evidence_summary: JsonValue
    frequency_hz_or_order: JsonValue
    amplitude_metric: AmplitudeMetric
    confidence_0_to_1: float | None
    quick_checks: list[JsonValue]


class Finding(FindingRequired, total=False):
    finding_type: str
    finding_key: str
    severity: str
    source: str
    confidence: float | None
    confidence_label_key: str
    confidence_tone: str
    confidence_pct: str
    matched_points: list[MatchedPoint]
    location_hotspot: LocationHotspot | None
    strongest_location: str | None
    strongest_speed_band: str | None
    dominant_phase: str | None
    peak_speed_kmh: float | None
    speed_window_kmh: list[float] | None
    dominance_ratio: float | None
    localization_confidence: float
    weak_spatial_separation: bool
    corroborating_locations: int
    diffuse_excitation: bool
    phase_evidence: PhaseEvidence | None
    evidence_metrics: FindingEvidenceMetrics
    next_sensor_move: JsonValue
    actions: list[TestStep]
    _ranking_score: float
    peak_classification: str
    phase_presence: dict[str, float] | None
    signatures_observed: list[str]
    grouped_count: int
    order: str
    diagnostic_caveat: JsonValue


class TopCause(TypedDict, total=False):
    finding_id: str
    source: str
    confidence: float | None
    confidence_label_key: str
    confidence_tone: str
    confidence_pct: str
    order: str
    signatures_observed: list[str]
    grouped_count: int
    strongest_location: str | None
    dominance_ratio: float | None
    strongest_speed_band: str | None
    weak_spatial_separation: bool
    diffuse_excitation: bool
    diagnostic_caveat: JsonValue
    phase_evidence: PhaseEvidence | None


CandidateFinding: TypeAlias = Finding | TopCause


class SpeedStats(TypedDict):
    min_kmh: float | None
    max_kmh: float | None
    mean_kmh: float | None
    stddev_kmh: float | None
    range_kmh: float | None
    steady_speed: bool


class PhaseSpeedStats(SpeedStats):
    sample_count: int


class PhaseSummary(TypedDict):
    phase_counts: dict[str, int]
    phase_pcts: dict[str, float]
    total_samples: int
    segment_count: int
    has_cruise: bool
    has_acceleration: bool
    cruise_pct: float
    idle_pct: float
    speed_unknown_pct: float


class SpeedBreakdownRow(TypedDict):
    speed_range: str
    count: int
    mean_vibration_strength_db: float | None
    max_vibration_strength_db: float | None


class PhaseSpeedBreakdownRow(TypedDict):
    phase: str
    count: int
    mean_speed_kmh: float | None
    max_speed_kmh: float | None
    mean_vibration_strength_db: float | None
    max_vibration_strength_db: float | None


class PhaseTimelineEntry(TypedDict):
    phase: str
    start_t_s: float | None
    end_t_s: float | None
    speed_min_kmh: float | None
    speed_max_kmh: float | None
    has_fault_evidence: bool


class PhaseSegmentSummary(TypedDict):
    phase: str
    start_idx: int
    end_idx: int
    start_t_s: float | None
    end_t_s: float | None
    speed_min_kmh: float | None
    speed_max_kmh: float | None
    sample_count: int


class OriginSummary(TypedDict, total=False):
    location: str
    alternative_locations: list[str]
    source: str
    dominance_ratio: float | None
    weak_spatial_separation: bool
    speed_band: str | None
    dominant_phase: str | None
    explanation: JsonValue


class AccelStatistics(TypedDict):
    accel_x_vals: list[float]
    accel_y_vals: list[float]
    accel_z_vals: list[float]
    accel_mag_vals: list[float]
    amp_metric_values: list[float]
    sat_count: int
    sensor_limit: float | None
    x_mean: float | None
    x_var: float | None
    y_mean: float | None
    y_var: float | None
    z_mean: float | None
    z_var: float | None


class RunSuitabilityCheck(TypedDict):
    check: str
    check_key: str
    state: str
    explanation: JsonValue


class _SummaryDataRequired(TypedDict):
    """Fields always present in the analysis summary payload."""

    file_name: str
    run_id: str
    rows: int
    duration_s: float
    record_length: str
    lang: str
    report_date: JsonValue
    start_time_utc: JsonValue
    end_time_utc: JsonValue
    sensor_model: JsonValue
    firmware_version: JsonValue
    raw_sample_rate_hz: float | None
    feature_interval_s: float | None
    fft_window_size_samples: JsonValue
    fft_window_type: JsonValue
    peak_picker_method: JsonValue
    accel_scale_g_per_lsb: float | None
    incomplete_for_order_analysis: bool
    metadata: MetadataDict
    warnings: list[JsonObject]
    speed_breakdown: list[SpeedBreakdownRow]
    phase_speed_breakdown: list[PhaseSpeedBreakdownRow]
    phase_segments: list[PhaseSegmentSummary]
    run_noise_baseline_db: float | None
    speed_breakdown_skipped_reason: I18nRef | None
    findings: list[Finding]
    top_causes: list[TopCause]
    most_likely_origin: OriginSummary
    test_plan: list[TestStep]
    phase_timeline: list[PhaseTimelineEntry]
    speed_stats: SpeedStats
    speed_stats_by_phase: dict[str, PhaseSpeedStats]
    phase_info: PhaseSummary
    sensor_locations: list[str]
    sensor_locations_connected_throughout: list[str]
    sensor_count_used: int
    sensor_intensity_by_location: list[IntensityRow]
    run_suitability: list[RunSuitabilityCheck]
    data_quality: JsonObject


class SummaryData(_SummaryDataRequired, total=False):
    """Full analysis summary payload.

    Required fields are always set by :func:`build_summary_payload`.
    Optional fields are set later in the pipeline or may be removed:

    * ``samples`` – present unless ``include_samples=False`` removes it.
    * ``plots`` – set by :func:`_plot_data` after initial assembly.
    * ``analysis_metadata`` – set by post-analysis workers.
    """

    samples: list[Sample]
    plots: PlotDataResult
    analysis_metadata: JsonObject


PhaseLabel: TypeAlias = DrivingPhase | str
PhaseLabels: TypeAlias = Sequence[PhaseLabel]
Translator: TypeAlias = Callable[[str], str]


def is_finding(value: object) -> TypeGuard[Finding]:
    """Narrow a runtime value to the canonical finding shape."""
    return isinstance(value, dict)


def is_top_cause(value: object) -> TypeGuard[TopCause]:
    """Narrow a runtime value to the top-cause summary shape."""
    return isinstance(value, dict)


class FindingsBuilder(Protocol):
    """Keyword-only callable contract for summary finding builders."""

    def __call__(
        self,
        *,
        metadata: MetadataDict,
        samples: list[Sample],
        speed_sufficient: bool,
        steady_speed: bool,
        speed_stddev_kmh: float | None,
        speed_non_null_pct: float,
        raw_sample_rate_hz: float | None,
        lang: str = "en",
        per_sample_phases: Sequence[DrivingPhase | str] | None = None,
        run_noise_baseline_g: float | None = None,
    ) -> list[Finding]: ...
