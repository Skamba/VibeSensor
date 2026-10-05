"""Shared exact analysis/history view shapes used by boundary and HTTP layers.

These TypedDicts are the single semantic owner for stable analysis/history
concepts that must be understood by both persistence-boundary payloads and
the HTTP/OpenAPI response schema.
"""

from __future__ import annotations

from typing import TypedDict

from pydantic import ConfigDict, with_config

__all__ = [
    "FindingEvidenceMetrics",
    "LocationHotspotPayload",
    "MatchedPoint",
    "PeakTableRow",
    "PhaseEvidence",
    "PhaseSpeedBreakdownRow",
    "PlotDataResult",
    "SpeedBreakdownRow",
]

_IGNORE_EXTRA = ConfigDict(extra="ignore")


@with_config(_IGNORE_EXTRA)
class PeakTableRow(TypedDict):
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


@with_config(_IGNORE_EXTRA)
class MatchedPoint(TypedDict, total=False):
    """HTTP contract for one serialized finding matched-point observation."""

    t_s: float | None
    speed_kmh: float | None
    predicted_hz: float | None
    matched_hz: float | None
    rel_error: float | None
    amp: float | None
    location: str | None
    phase: str | None
    heard: bool


@with_config(_IGNORE_EXTRA)
class PhaseEvidence(TypedDict, total=False):
    """HTTP contract for optional driving-phase evidence attached to a finding."""

    cruise_fraction: float | None
    phases_detected: list[str]


@with_config(_IGNORE_EXTRA)
class LocationHotspotPayload(TypedDict, total=False):
    """HTTP contract for serialized location-hotspot evidence."""

    dominance_ratio: float | None
    location_count: int | None
    top_location: str | None
    ambiguous_location: bool | None
    ambiguous_locations: list[str]
    localization_confidence: float | None
    weak_spatial_separation: bool | None


@with_config(_IGNORE_EXTRA)
class FindingEvidenceMetrics(TypedDict, total=False):
    """HTTP contract for serialized evidence metrics attached to a finding."""

    match_rate: float | None
    global_match_rate: float | None
    focused_speed_band: str | None
    mean_relative_error: float | None
    mean_noise_floor_db: float | None
    snr_db: float | None
    vibration_strength_db: float | None
    possible_samples: int | None
    matched_samples: int | None
    frequency_correlation: float | None
    per_phase_confidence: dict[str, float] | None
    phases_with_evidence: int | None
    presence_ratio: float | None
    median_intensity_db: float | None
    p95_intensity_db: float | None
    max_intensity_db: float | None
    burstiness: float | None
    run_noise_baseline_db: float | None
    median_relative_to_run_noise: float | None
    p95_relative_to_run_noise: float | None
    sample_count: int | None
    total_samples: int | None
    spatial_concentration: float | None
    spatial_uniformity: float | None
    speed_uniformity: float | None


@with_config(_IGNORE_EXTRA)
class SpeedBreakdownRow(TypedDict):
    """Typed HTTP contract for one speed-band aggregate row."""

    speed_range: str
    count: int
    mean_vibration_strength_db: float | None
    max_vibration_strength_db: float | None


@with_config(_IGNORE_EXTRA)
class PhaseSpeedBreakdownRow(TypedDict):
    """Typed HTTP contract for one phase-aware speed aggregate row."""

    phase: str
    count: int
    mean_speed_kmh: float | None
    max_speed_kmh: float | None
    mean_vibration_strength_db: float | None
    max_vibration_strength_db: float | None


@with_config(_IGNORE_EXTRA)
class PlotDataResult(TypedDict):
    """Typed HTTP contract for the ``plots`` section of a run summary.

    Only the ranked peak table is produced. Runs persisted by older versions may
    still carry additional plot series; they are ignored on validation.
    """

    peaks_table: list[PeakTableRow]
