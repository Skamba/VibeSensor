"""Split finding payload contracts used to compose the shared finding wrapper."""

from __future__ import annotations

from typing import Required, TypedDict

from vibesensor.shared.types.analysis_views import (
    FindingEvidenceMetrics,
    LocationHotspotPayload,
    MatchedPoint,
    PhaseEvidence,
)
from vibesensor.shared.types.json_types import JsonSchemaValue

__all__ = [
    "AmplitudeMetric",
    "FindingCorePayload",
    "FindingPayload",
    "FindingPresentationPayload",
]


class AmplitudeMetric(TypedDict, total=False):
    """HTTP contract for finding amplitude/strength metadata."""

    name: str | None
    value: float | None
    units: str | None
    definition: JsonSchemaValue


class FindingCorePayload(TypedDict, total=False):
    """Internal domain-owned finding payload fields."""

    finding_id: Required[str]
    finding_key: str | None
    suspected_source: Required[str]
    confidence: Required[float | None]
    finding_kind: str | None
    severity: str | None
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


class FindingPresentationPayload(TypedDict, total=False):
    """Internal rendering-oriented finding metadata."""

    evidence_summary: Required[str]
    frequency_hz_or_order: Required[float | str]
    amplitude_metric: Required[AmplitudeMetric]
    confidence_label_key: str | None
    confidence_reason: str | None
    confidence_tone: str | None
    confidence_pct: str | None


class FindingPayload(FindingCorePayload, FindingPresentationPayload, total=False):
    """Canonical shared contract for one serialized finding payload.

    Boundary serializers and HTTP models should import this TypedDict directly
    so future field changes have one source of truth. It intentionally includes
    a few presentation-oriented projections (``evidence_summary``,
    ``frequency_hz_or_order``, ``amplitude_metric``, and the confidence label
    fields) alongside the domain-owned finding data.
    """
