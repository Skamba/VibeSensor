"""Pure report-domain interpretation helpers for history/PDF workflows."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import mean as _mean

from vibesensor.domain import Finding, TestRun, VibrationOrigin
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.types.json_types import JsonObject


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
    sensor_intensity: Sequence[JsonObject],
) -> dict[str, list[float]]:
    """Collect per-location intensity values from summary sensor intensity rows."""
    amp_by_location: dict[str, list[float]] = defaultdict(list)
    for row in sensor_intensity:
        if not isinstance(row, dict):
            continue
        location = str(row.get("location") or "").strip()
        p95_val = _as_float(row.get("p95_intensity_db"))
        p95 = p95_val if p95_val is not None else _as_float(row.get("mean_intensity_db"))
        if location and p95 is not None and p95 > 0:
            amp_by_location[location].append(p95)
    return amp_by_location


def compute_location_hotspot_rows(
    sensor_intensity: Sequence[JsonObject],
) -> list[JsonObject]:
    """Pre-compute location hotspot rows from sensor intensity data."""
    if not sensor_intensity:
        return []
    amp_by_location = collect_location_intensity(sensor_intensity)
    hotspot_rows: list[JsonObject] = [
        {
            "location": location,
            "count": len(amps),
            "unit": "db",
            "peak_value": max(amps),
            "mean_value": _mean(amps),
        }
        for location, amps in amp_by_location.items()
    ]
    hotspot_rows.sort(
        key=lambda row: (
            _as_float(row.get("peak_value")) or 0.0,
            _as_float(row.get("mean_value")) or 0.0,
        ),
        reverse=True,
    )
    return hotspot_rows


def sensor_fallback_strength_db(sensor_intensity: Sequence[JsonObject]) -> float | None:
    """Return the best sensor-intensity dB as a last-resort fallback."""
    sensor_rows = [
        _as_float(row.get("p95_intensity_db")) for row in sensor_intensity if isinstance(row, dict)
    ]
    return max((value for value in sensor_rows if value is not None), default=None)


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
) -> list[JsonObject]:
    """Filter sensor intensity rows to only active locations."""
    active_locations = set(sensor_locations_active)
    if active_locations:
        return [
            row
            for row in raw_sensor_intensity_all
            if isinstance(row, dict) and str(row.get("location") or "") in active_locations
        ]
    return [row for row in raw_sensor_intensity_all if isinstance(row, dict)]


def resolve_primary_report_facts(
    *,
    aggregate: TestRun,
    origin_location: str,
    sensor_locations_active: Sequence[str],
    sensor_intensity: Sequence[JsonObject],
) -> PrimaryReportFacts:
    """Resolve the domain-derived facts for the report's primary candidate."""
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
    )
