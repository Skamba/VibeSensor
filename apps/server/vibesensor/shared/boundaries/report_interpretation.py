"""Pure report-domain interpretation helpers for history/PDF workflows."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import mean as _mean

from vibesensor.domain import (
    Finding,
    FindingEvidence,
    LocationHotspot,
    LocationHotspotRow,
    LocationIntensitySummary,
    TestRun,
    VibrationOrigin,
)
from vibesensor.shared.json_utils import as_float_or_none as _as_float


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


def collect_location_intensity(
    sensor_intensity: Sequence[LocationIntensitySummary],
) -> dict[str, list[float]]:
    """Collect per-location intensity values from summary sensor intensity rows."""
    amp_by_location: dict[str, list[float]] = defaultdict(list)
    for row in sensor_intensity:
        location = row.location.strip()
        p95 = row.p95_intensity_db if row.p95_intensity_db is not None else row.mean_intensity_db
        if location and p95 is not None and p95 > 0:
            amp_by_location[location].append(p95)
    return amp_by_location


def compute_location_hotspot_rows(
    sensor_intensity: Sequence[LocationIntensitySummary],
) -> list[LocationHotspotRow]:
    """Pre-compute location hotspot rows from sensor intensity data."""
    if not sensor_intensity:
        return []
    amp_by_location = collect_location_intensity(sensor_intensity)
    hotspot_rows = [
        LocationHotspotRow(
            location=location,
            count=len(amps),
            unit="db",
            peak_value=max(amps),
            mean_value=_mean(amps),
        )
        for location, amps in amp_by_location.items()
    ]
    hotspot_rows.sort(
        key=lambda row: (row.peak_value, row.mean_value),
        reverse=True,
    )
    return hotspot_rows


def sensor_fallback_strength_db(
    sensor_intensity: Sequence[LocationIntensitySummary],
) -> float | None:
    """Return the best sensor-intensity dB as a last-resort fallback."""
    return max(
        (row.p95_intensity_db for row in sensor_intensity if row.p95_intensity_db is not None),
        default=None,
    )


def tire_spec_text(meta: Mapping[str, object]) -> str | None:
    """Format tire specification text from metadata when present."""
    tire_width_mm = _as_float(meta.get("tire_width_mm"))
    tire_aspect_pct = _as_float(meta.get("tire_aspect_pct"))
    rim_in = _as_float(meta.get("rim_in"))
    if not (
        tire_width_mm is not None
        and tire_aspect_pct is not None
        and rim_in is not None
        and tire_width_mm > 0
        and tire_aspect_pct > 0
        and rim_in > 0
    ):
        return None
    return f"{tire_width_mm:g}/{tire_aspect_pct:g}R{rim_in:g}"


def filter_active_sensor_intensity(
    raw_sensor_intensity_all: Sequence[object],
    sensor_locations_active: Sequence[str],
) -> list[LocationIntensitySummary]:
    """Filter sensor intensity rows to only active locations."""
    active_locations = set(sensor_locations_active)
    rows: list[LocationIntensitySummary] = []
    for row in raw_sensor_intensity_all:
        if isinstance(row, LocationIntensitySummary):
            typed_row = row
        elif isinstance(row, Mapping):
            typed_row = LocationIntensitySummary.from_dict(row)
        else:
            continue
        if active_locations and typed_row.location not in active_locations:
            continue
        rows.append(typed_row)
    return rows


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
