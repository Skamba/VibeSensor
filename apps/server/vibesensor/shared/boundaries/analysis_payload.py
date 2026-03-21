"""Boundary serialization types for analysis payloads.

These TypedDicts define the wire/persistence shapes for analysis data
that crosses the domain-adapter boundary.  Internal analysis logic uses
domain objects (e.g. ``OrderMatchObservation``); these types exist only
for serialization into ``FindingPayload`` and similar boundary payloads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, NotRequired, Required, TypedDict

from vibesensor.domain import OrderMatchObservation
from vibesensor.shared.types.json_types import JsonObject, JsonValue

if TYPE_CHECKING:
    from vibesensor.shared.boundaries.vibration_origin import SuspectedVibrationOrigin

__all__ = [
    "AmpVsPhaseRow",
    "AmplitudeMetric",
    "AnalysisSummary",
    "FindingEvidenceMetrics",
    "FindingPayload",
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
    "RunSuitabilityCheck",
    "SpectrogramResult",
    "SpeedBreakdownRow",
    "matched_point_from_observation",
]


# ---------------------------------------------------------------------------
# Small leaf shapes (no forward-references)
# ---------------------------------------------------------------------------


class PeakTableRow(TypedDict):
    """Shape of a single row in the ranked peak table."""

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


class MatchedPoint(TypedDict, total=False):
    """Serialization shape for a single matched frequency observation.

    This is the boundary representation stored in ``FindingPayload.matched_points``.
    Internal analysis code uses :class:`~vibesensor.domain.OrderMatchObservation`.
    """

    t_s: float | None
    speed_kmh: float | None
    predicted_hz: float
    matched_hz: float
    rel_error: float
    amp: float
    location: str
    phase: str | None


class PhaseEvidence(TypedDict, total=False):
    """Phase context evidence attached to a finding (serialization shape)."""

    cruise_fraction: float
    phases_detected: list[str]


class AmplitudeMetric(TypedDict):
    """Presentation-only vibration-strength summary attached to a finding payload."""

    name: str
    value: float | None
    units: str
    definition: JsonValue


class LocationHotspotPayload(TypedDict, total=False):
    dominance_ratio: float | None
    location_count: int
    top_location: str
    second_location: str | None
    ambiguous_location: bool
    ambiguous_locations: list[str]
    localization_confidence: float
    weak_spatial_separation: bool


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


class RunSuitabilityCheck(TypedDict):
    check: str
    check_key: str
    state: str
    explanation: JsonValue


class SummaryWarningPayload(TypedDict):
    code: str
    severity: Literal["warn", "error"]
    applies_to: str
    title: JsonValue
    detail: JsonValue


class TestPlanStepPayload(TypedDict):
    action_id: str
    what: str
    why: str | None
    confirm: str | None
    falsify: str | None
    eta: str | None


class PhaseTimelineEntryPayload(TypedDict):
    phase: str
    start_t_s: float | None
    end_t_s: float | None
    speed_min_kmh: float | None
    speed_max_kmh: float | None
    has_fault_evidence: bool


class PhaseSegmentSummaryPayload(TypedDict):
    phase: str
    start_idx: int
    end_idx: int
    start_t_s: float | None
    end_t_s: float | None
    speed_min_kmh: float | None
    speed_max_kmh: float | None
    sample_count: int


class SpeedStatsPayload(TypedDict):
    min_kmh: float | None
    max_kmh: float | None
    mean_kmh: float | None
    stddev_kmh: float | None
    range_kmh: float | None
    steady_speed: bool
    sample_count: int


class PhaseInfoPayload(TypedDict):
    phase_counts: dict[str, int]
    phase_pcts: dict[str, float]
    total_samples: int
    segment_count: int
    has_cruise: bool
    has_acceleration: bool
    cruise_pct: float
    idle_pct: float
    speed_unknown_pct: float


class OutlierSummaryPayload(TypedDict):
    count: int
    outlier_count: int
    outlier_pct: float
    lower_bound: float | None
    upper_bound: float | None


class DataQualityRequiredMissingPctPayload(TypedDict):
    t_s: float
    speed_kmh: float
    accel_x: float
    accel_y: float
    accel_z: float


class DataQualitySpeedCoveragePayload(TypedDict):
    non_null_pct: float
    min_kmh: float | None
    max_kmh: float | None
    mean_kmh: float | None
    stddev_kmh: float | None
    count_non_null: int


class DataQualityAccelSanityPayload(TypedDict):
    x_mean: float | None
    x_variance: float | None
    y_mean: float | None
    y_variance: float | None
    z_mean: float | None
    z_variance: float | None
    sensor_limit: float | None
    saturation_count: int | None


class DataQualityOutliersPayload(TypedDict):
    accel_magnitude: OutlierSummaryPayload
    amplitude_metric: OutlierSummaryPayload


class DataQualityPayload(TypedDict):
    required_missing_pct: DataQualityRequiredMissingPctPayload
    speed_coverage: DataQualitySpeedCoveragePayload
    accel_sanity: DataQualityAccelSanityPayload
    outliers: DataQualityOutliersPayload


class StrengthBucketDistributionPayload(TypedDict):
    total: int
    counts: dict[str, int]
    percent_time_l0: float
    percent_time_l1: float
    percent_time_l2: float
    percent_time_l3: float
    percent_time_l4: float
    percent_time_l5: float


class PhaseIntensityStatsPayload(TypedDict):
    count: int
    mean_intensity_db: float | None
    max_intensity_db: float | None


class LocationIntensitySummaryPayload(TypedDict):
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
    strength_bucket_distribution: StrengthBucketDistributionPayload
    phase_intensity: dict[str, PhaseIntensityStatsPayload] | None


# ---------------------------------------------------------------------------
# Composite payload shapes
# ---------------------------------------------------------------------------


class FindingPayload(TypedDict, total=False):
    """Serialized finding payload used at transport and persistence boundaries.

    This payload intentionally remains a superset of the domain
    :class:`~vibesensor.domain.Finding`:

    * direct domain fields are copied across unchanged,
    * ``evidence_summary``, ``frequency_hz_or_order``, ``amplitude_metric``,
      and the confidence label fields are presentation-oriented projections
      computed during ``finding_payload_from_domain()``,
    * ``matched_points``, ``phase_evidence``, ``evidence_metrics``,
      ``location_hotspot``, and ``signatures_observed`` are boundary mirrors
      of richer domain sub-objects.
    """

    # Direct domain-owned finding state.
    finding_id: Required[str]
    finding_key: str
    suspected_source: Required[str]
    confidence: Required[float | None]
    finding_kind: str
    severity: str
    strongest_location: str | None
    strongest_speed_band: str | None
    dominant_phase: str | None
    dominance_ratio: float | None
    weak_spatial_separation: bool
    diffuse_excitation: bool
    ranking_score: float
    peak_classification: str
    order: str

    # Presentation-only projections computed from domain-owned data.
    evidence_summary: Required[JsonValue]
    frequency_hz_or_order: Required[JsonValue]
    amplitude_metric: Required[AmplitudeMetric]
    confidence_label_key: str
    confidence_tone: str
    confidence_pct: str

    # Boundary mirrors of richer nested domain objects.
    matched_points: list[MatchedPoint]
    location_hotspot: LocationHotspotPayload | None
    phase_evidence: PhaseEvidence | None
    evidence_metrics: FindingEvidenceMetrics
    signatures_observed: list[str]


# ---------------------------------------------------------------------------
# Plot-data boundary shapes (moved from use_cases/diagnostics/plots.py)
# ---------------------------------------------------------------------------


class SpectrogramResult(TypedDict, total=False):
    """Shape returned by spectrogram builders."""

    x_axis: Required[str]
    x_label_key: Required[str]
    x_bins: Required[list[float]]
    y_bins: Required[list[float]]
    cells: Required[list[list[float]]]
    max_amp: Required[float]
    x_bin_width: float
    y_bin_width: float


class MatchedAmpVsSpeedSeries(TypedDict):
    """Per-finding matched-point series for amp-vs-speed."""

    label: str
    points: list[tuple[float, float]]


class FreqVsSpeedByFindingSeries(TypedDict):
    """Per-finding frequency-vs-speed series with predicted overlay."""

    label: str
    matched: list[tuple[float, float]]
    predicted: list[tuple[float, float]]


class AmpVsPhaseRow(TypedDict):
    """A single phase-grouped vibration row."""

    phase: str
    count: int
    mean_vib_db: float
    max_vib_db: float | None
    mean_speed_kmh: float | None


class PhaseSegmentOut(TypedDict):
    """Serialised driving-phase segment for plot consumers."""

    phase: str
    start_t_s: float | None
    end_t_s: float | None


class PhaseBoundary(TypedDict):
    """Phase boundary marker for plot overlay."""

    phase: str
    t_s: float | None
    end_t_s: float | None


class PlotDataResult(TypedDict):
    """Shape returned by the plot-data orchestration layer."""

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


class AnalysisSummary(TypedDict):
    """Full analysis summary payload.

    Required fields are always set by :func:`build_summary_payload`.
    Optional fields are set later in the pipeline or may be removed:

    * ``samples`` – present unless ``include_samples=False`` removes it.
    * ``plots`` – set by :func:`_plot_data` after initial assembly.
    * ``analysis_metadata`` – set by post-analysis workers.
    """

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
    metadata: JsonObject
    warnings: list[SummaryWarningPayload]
    speed_breakdown: list[SpeedBreakdownRow]
    phase_speed_breakdown: list[PhaseSpeedBreakdownRow]
    phase_segments: list[PhaseSegmentSummaryPayload]
    run_noise_baseline_db: float | None
    speed_breakdown_skipped_reason: JsonObject | None
    findings: list[FindingPayload]
    top_causes: list[FindingPayload]
    most_likely_origin: SuspectedVibrationOrigin
    test_plan: list[TestPlanStepPayload]
    phase_timeline: list[PhaseTimelineEntryPayload]
    speed_stats: SpeedStatsPayload
    speed_stats_by_phase: dict[str, SpeedStatsPayload]
    phase_info: PhaseInfoPayload
    sensor_locations: list[str]
    sensor_locations_connected_throughout: list[str]
    sensor_count_used: int
    sensor_intensity_by_location: list[LocationIntensitySummaryPayload]
    run_suitability: list[RunSuitabilityCheck]
    data_quality: DataQualityPayload
    samples: NotRequired[list[JsonObject]]
    plots: NotRequired[PlotDataResult]
    analysis_metadata: NotRequired[JsonObject]


# ---------------------------------------------------------------------------
# Serializer helpers
# ---------------------------------------------------------------------------


def matched_point_from_observation(obs: OrderMatchObservation) -> MatchedPoint:
    """Serialize a domain ``OrderMatchObservation`` to a boundary ``MatchedPoint`` dict."""
    return MatchedPoint(
        t_s=obs.t_s,
        speed_kmh=obs.speed_kmh,
        predicted_hz=obs.predicted_hz,
        matched_hz=obs.matched_hz,
        rel_error=obs.rel_error,
        amp=obs.amp,
        location=obs.location,
        phase=obs.phase,
    )
