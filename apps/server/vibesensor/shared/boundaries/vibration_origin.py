"""Boundary decoders and projectors for VibrationOrigin payload shapes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict

from vibesensor.domain.finding import Finding, VibrationSource
from vibesensor.domain.location_hotspot import LocationHotspot
from vibesensor.domain.vibration_origin import VibrationOrigin
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.types.json_types import JsonValue


def location_hotspot_from_payload(payload: dict[str, object]) -> LocationHotspot:
    """Decode a persisted or transported hotspot payload into a domain object."""
    alts = payload.get("alternative_locations") or payload.get("ambiguous_locations") or []
    if not isinstance(alts, (list, tuple)):
        alts = []
    alt_strings = [str(a) for a in alts]

    # Include second_location as an alternative if not already present
    second_loc = str(payload.get("second_location") or "").strip()
    if second_loc and second_loc not in alt_strings:
        alt_strings.append(second_loc)

    dom_raw = payload.get("dominance_ratio")
    dominance_ratio: float | None = None
    if dom_raw is not None:
        try:
            dominance_ratio = float(dom_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pass

    loc_conf_raw = payload.get("localization_confidence")
    localization_confidence: float | None = None
    if loc_conf_raw is not None:
        try:
            localization_confidence = float(loc_conf_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pass

    loc_count_raw = payload.get("location_count")
    loc_count: int | None = None
    if loc_count_raw is not None:
        try:
            loc_count = int(loc_count_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pass

    return LocationHotspot(
        strongest_location=str(payload.get("top_location", payload.get("location", "")) or ""),
        dominance_ratio=dominance_ratio,
        localization_confidence=localization_confidence,
        weak_spatial_separation=bool(payload.get("weak_spatial_separation", False)),
        ambiguous=bool(payload.get("ambiguous_location", payload.get("ambiguous", False))),
        alternative_locations=tuple(alt_strings),
        location_count=loc_count,
    )


__all__ = [
    "SuspectedVibrationOrigin",
    "origin_payload_from_finding",
    "vibration_origin_from_payload",
]


class SuspectedVibrationOrigin(TypedDict, total=False):
    """Boundary-only JSON payload shape for origin data.

    This TypedDict is the serialization format for
    ``AnalysisSummary.most_likely_origin`` and persisted run payloads.
    Domain code must use :class:`~vibesensor.domain.VibrationOrigin`
    instead.  This type exists solely at ingress/egress boundaries.
    """

    location: str
    alternative_locations: list[str]
    suspected_source: str
    dominance_ratio: float | None
    weak_spatial_separation: bool
    speed_band: str | None
    dominant_phase: str | None
    explanation: JsonValue


def _source_from_payload(
    payload: Mapping[str, object],
    *,
    fallback: VibrationSource | None = None,
) -> VibrationSource:
    if fallback is not None:
        return fallback
    raw_source = str(payload.get("suspected_source") or "").strip().lower()
    try:
        return VibrationSource(raw_source)
    except ValueError:
        return VibrationSource.UNKNOWN


def vibration_origin_from_payload(
    payload: Mapping[str, object],
    *,
    hotspot: LocationHotspot | None = None,
    suspected_source: VibrationSource | None = None,
    dominance_ratio: float | None = None,
    speed_band: str | None = None,
) -> VibrationOrigin:
    """Decode a finding-shaped payload into a domain VibrationOrigin."""
    hotspot_raw = payload.get("location_hotspot")
    resolved_hotspot = hotspot
    if resolved_hotspot is None and isinstance(hotspot_raw, dict):
        resolved_hotspot = location_hotspot_from_payload(hotspot_raw)

    resolved_speed_band = speed_band
    if resolved_speed_band is None:
        raw_speed_band = payload.get("strongest_speed_band") or payload.get("speed_band")
        resolved_speed_band = (
            str(raw_speed_band).strip() or None if raw_speed_band is not None else None
        )

    resolved_reason = payload.get("evidence_summary")
    reason = str(resolved_reason).strip() if isinstance(resolved_reason, str) else ""

    return VibrationOrigin.from_analysis_inputs(
        suspected_source=_source_from_payload(payload, fallback=suspected_source),
        hotspot=resolved_hotspot,
        dominance_ratio=(
            dominance_ratio
            if dominance_ratio is not None
            else _as_float(payload.get("dominance_ratio"))
        ),
        speed_band=resolved_speed_band,
        dominant_phase=str(payload.get("dominant_phase") or "").strip() or None,
        reason=reason,
    )


def origin_payload_from_finding(
    finding: Finding,
) -> SuspectedVibrationOrigin:
    """Project a domain finding's origin into the canonical boundary payload shape."""
    origin = VibrationOrigin.from_finding(finding)

    if origin is None:
        return {}

    return {
        "location": origin.projected_location,
        "alternative_locations": list(origin.alternative_locations),
        "suspected_source": str(origin.suspected_source),
        "dominance_ratio": origin.dominance_ratio,
        "weak_spatial_separation": origin.weak_spatial_separation,
        "speed_band": origin.speed_band,
        "dominant_phase": origin.dominant_phase,
        "explanation": origin.explanation,
    }
