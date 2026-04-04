"""Primary-candidate projection helpers for history/PDF workflows."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from vibesensor.domain import (
    Finding,
    FindingEvidence,
    LocationHotspot,
    LocationIntensitySummary,
    TestRun,
    VibrationOrigin,
)
from vibesensor.shared.boundaries.reporting.sensor_facts import sensor_fallback_strength_db

__all__ = [
    "PrimaryReportFacts",
    "normalize_origin_location",
    "resolve_primary_report_facts",
    "resolve_report_origin",
]


@dataclass(frozen=True, slots=True)
class PrimaryReportFacts:
    """Semantic primary-candidate facts derived from the domain aggregate."""

    domain_primary: Finding | None
    primary_source: object | None
    primary_location: str | None
    primary_speed: str | None
    confidence: float
    sensor_count: int
    weak_spatial: bool
    has_reference_gaps: bool
    strength_db: float | None
    dominance_ratio: float | None
    location_hotspot: LocationHotspot | None
    evidence: FindingEvidence | None
    matched_evidence_window_count: int | None


def resolve_report_origin(
    aggregate: TestRun | None,
) -> VibrationOrigin | None:
    """Resolve report origin from the domain aggregate only."""
    if aggregate is None or aggregate.primary_finding is None:
        return None
    return VibrationOrigin.from_finding(aggregate.primary_finding)


def normalize_origin_location(origin: VibrationOrigin | None) -> str:
    """Return the report-ready origin location string."""
    if origin is None:
        return ""
    raw = origin.projected_location.strip()
    return "" if raw.lower() == "unknown" else raw


def resolve_primary_report_facts(
    *,
    aggregate: TestRun,
    origin_location: str,
    sensor_locations_active: Sequence[str],
    sensor_intensity: Sequence[LocationIntensitySummary],
) -> PrimaryReportFacts:
    """Resolve the domain-derived facts for the report's primary candidate.

    **strength_db precedence** (first non-None wins):

    1. Domain-derived: ``aggregate.top_strength_db()`` — the
       ``vibration_strength_db`` of the first effective top-cause finding,
       or the first finding with a non-None strength if no top-cause has one.
    2. Sensor-fallback: ``sensor_fallback_strength_db(sensor_intensity)`` —
       the maximum ``p95_intensity_db`` across all active sensor locations.
    3. None: if neither source provides a value, ``strength_db`` is ``None``
       and downstream tier/label logic must handle the absence.
    """
    effective = aggregate.effective_top_causes()
    domain_primary = effective[0] if effective else aggregate.primary_finding

    primary_source: object | None = None
    if domain_primary is not None:
        primary_source = domain_primary.suspected_source
        primary_location = origin_location or domain_primary.strongest_location or None
        primary_speed = domain_primary.strongest_speed_band
        confidence = domain_primary.effective_confidence
    else:
        primary_location = origin_location or None
        primary_speed = None
        confidence = 0.0

    strength_db = aggregate.top_strength_db()
    if strength_db is None:
        strength_db = sensor_fallback_strength_db(sensor_intensity)

    return PrimaryReportFacts(
        domain_primary=domain_primary,
        primary_source=primary_source,
        primary_location=primary_location,
        primary_speed=primary_speed,
        confidence=confidence,
        sensor_count=len(sensor_locations_active) or len(aggregate.capture.setup.sensors),
        weak_spatial=domain_primary.weak_spatial_separation if domain_primary else False,
        has_reference_gaps=aggregate.has_relevant_reference_gap(
            str(primary_source) if primary_source else "unknown",
        ),
        strength_db=strength_db,
        dominance_ratio=domain_primary.dominance_ratio if domain_primary else None,
        location_hotspot=domain_primary.location if domain_primary else None,
        evidence=domain_primary.evidence if domain_primary else None,
        matched_evidence_window_count=(
            len(domain_primary.matched_points)
            if domain_primary and domain_primary.matched_points
            else (
                domain_primary.evidence.matched_samples
                if domain_primary and domain_primary.evidence is not None
                else None
            )
        ),
    )
