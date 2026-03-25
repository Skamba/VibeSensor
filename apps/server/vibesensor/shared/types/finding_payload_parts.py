"""Internal finding payload-part contracts used by the finding encoder."""

from __future__ import annotations

from typing_extensions import TypedDict

from vibesensor.shared.types.analysis_views import (
    FindingEvidenceMetrics,
    LocationHotspotPayload,
    MatchedPoint,
    PhaseEvidence,
)
from vibesensor.shared.types.history_analysis_contracts import AmplitudeMetric

__all__ = ["FindingCorePayload", "FindingPresentationPayload"]


class FindingCorePayload(TypedDict, total=False):
    """Internal domain-owned finding payload fields."""

    finding_id: str
    finding_key: str | None
    suspected_source: str
    confidence: float | None
    finding_kind: str | None
    severity: str | None
    matched_points: list[MatchedPoint]
    location_hotspot: LocationHotspotPayload | None
    strongest_location: str | None
    strongest_speed_band: str | None
    dominant_phase: str | None
    dominance_ratio: float | None
    weak_spatial_separation: bool
    diffuse_excitation: bool
    phase_evidence: PhaseEvidence | None
    evidence_metrics: FindingEvidenceMetrics | None
    ranking_score: float | None
    peak_classification: str | None
    signatures_observed: list[str]
    order: str | None


class FindingPresentationPayload(TypedDict, total=False):
    """Internal rendering-oriented finding metadata."""

    evidence_summary: str
    frequency_hz_or_order: float | str
    amplitude_metric: AmplitudeMetric
    confidence_label_key: str | None
    confidence_tone: str | None
    confidence_pct: str | None
