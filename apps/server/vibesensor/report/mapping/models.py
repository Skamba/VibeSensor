"""Explicit intermediate models for summary-to-report mapping."""

from __future__ import annotations

from dataclasses import dataclass

from ...analysis._types import CandidateFinding, Finding, MetadataDict, OriginSummary, SpeedStats


@dataclass(frozen=True)
class ReportMappingContext:
    """Normalized structural context pulled from an analysis summary."""

    meta: MetadataDict
    car_name: str | None
    car_type: str | None
    date_str: str
    top_causes: list[CandidateFinding]
    findings_non_ref: list[Finding]
    findings: list[Finding]
    speed_stats: SpeedStats
    origin: OriginSummary
    origin_location: str
    sensor_locations_active: list[str]


@dataclass(frozen=True)
class PrimaryCandidateContext:
    """Primary report candidate resolved from top causes or findings."""

    primary_candidate: CandidateFinding | None
    primary_source: object
    primary_system: str
    primary_location: str
    primary_speed: str
    confidence: float
    sensor_count: int
    weak_spatial: bool
    has_reference_gaps: bool
    strength_db: float | None
    strength_text: str
    strength_band_key: str | None
    certainty_key: str
    certainty_label_text: str
    certainty_pct: str
    certainty_reason: str
    tier: str
