"""History and finding-oriented HTTP API models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

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
    analysis: ApiPayloadObject | None = None


class HistoryInsightWarningResponse(BaseModel):
    """Response body for a localized history/run trust warning."""

    code: str
    severity: Literal["warn", "error"]
    applies_to: str
    title: str
    detail: str | None = None


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


class HistoryInsightsResponse(_ExtraAllowBase):
    """Response body with aggregated diagnostic insights for a run."""

    run_id: str | None = None
    status: str | None = None
    warnings: list[HistoryInsightWarningResponse] = Field(default_factory=list)
    findings: list[FindingPayload] = Field(default_factory=list)
    top_causes: list[FindingPayload] = Field(default_factory=list)


class DeleteHistoryRunResponse(BaseModel):
    """Response body confirming deletion of a history run."""

    run_id: str
    status: str
