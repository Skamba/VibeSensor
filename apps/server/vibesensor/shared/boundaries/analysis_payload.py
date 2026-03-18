"""Boundary serialization types for analysis payloads.

These TypedDicts define the wire/persistence shapes for analysis data
that crosses the domain-adapter boundary.  Internal analysis logic uses
domain objects (e.g. ``OrderMatchObservation``); these types exist only
for serialization into ``FindingPayload`` and similar boundary payloads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NotRequired, Required, TypedDict

from vibesensor.domain import OrderMatchObservation
from vibesensor.shared.types.json_types import JsonObject, JsonValue

if TYPE_CHECKING:
    from vibesensor.shared.boundaries.vibration_origin import SuspectedVibrationOrigin
    from vibesensor.use_cases.diagnostics.plots import PlotDataResult

__all__ = [
    "AmplitudeMetric",
    "AnalysisSummary",
    "FindingEvidenceMetrics",
    "FindingPayload",
    "LocationHotspotPayload",
    "MatchedPoint",
    "PhaseEvidence",
    "PhaseSpeedBreakdownRow",
    "RunSuitabilityCheck",
    "SpeedBreakdownRow",
    "matched_point_from_observation",
]


# ---------------------------------------------------------------------------
# Small leaf shapes (no forward-references)
# ---------------------------------------------------------------------------


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
    name: str
    value: float | None
    units: str
    definition: JsonValue


class LocationHotspotPayload(TypedDict, total=False):
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
    per_bin_results: list[LocationHotspotPayload]


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


# ---------------------------------------------------------------------------
# Composite payload shapes
# ---------------------------------------------------------------------------


class FindingPayload(TypedDict, total=False):
    finding_id: Required[str]
    suspected_source: Required[str]
    evidence_summary: Required[JsonValue]
    frequency_hz_or_order: Required[JsonValue]
    amplitude_metric: Required[AmplitudeMetric]
    confidence: Required[float | None]
    quick_checks: Required[list[JsonValue]]
    finding_kind: str
    finding_key: str
    severity: str
    confidence_label_key: str
    confidence_tone: str
    confidence_pct: str
    matched_points: list[MatchedPoint]
    location_hotspot: LocationHotspotPayload | None
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
    actions: list[JsonObject]
    ranking_score: float
    peak_classification: str
    phase_presence: dict[str, float] | None
    signatures_observed: list[str]
    grouped_count: int
    order: str
    diagnostic_caveat: JsonValue


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
    warnings: list[JsonObject]
    speed_breakdown: list[SpeedBreakdownRow]
    phase_speed_breakdown: list[PhaseSpeedBreakdownRow]
    phase_segments: list[JsonObject]
    run_noise_baseline_db: float | None
    speed_breakdown_skipped_reason: JsonObject | None
    findings: list[FindingPayload]
    top_causes: list[FindingPayload]
    most_likely_origin: SuspectedVibrationOrigin
    test_plan: list[JsonObject]
    phase_timeline: list[JsonObject]
    speed_stats: JsonObject
    speed_stats_by_phase: dict[str, JsonObject]
    phase_info: JsonObject
    sensor_locations: list[str]
    sensor_locations_connected_throughout: list[str]
    sensor_count_used: int
    sensor_intensity_by_location: list[JsonObject]
    run_suitability: list[RunSuitabilityCheck]
    data_quality: JsonObject
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
