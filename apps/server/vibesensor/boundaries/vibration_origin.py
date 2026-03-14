"""Boundary decoders and projectors for VibrationOrigin payload shapes."""

from __future__ import annotations

from collections.abc import Mapping

from ..analysis._types import SuspectedVibrationOrigin
from ..domain.finding import Finding, VibrationSource
from ..domain.location_hotspot import LocationHotspot
from ..domain.vibration_origin import VibrationOrigin
from .location_hotspot import location_hotspot_from_payload

__all__ = ["origin_payload_from_finding", "vibration_origin_from_payload"]


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _source_from_payload(
    payload: Mapping[str, object],
    *,
    fallback: VibrationSource | None = None,
) -> VibrationSource:
    if fallback is not None:
        return fallback
    raw_source = str(payload.get("suspected_source") or payload.get("source") or "").strip().lower()
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
    fallback: Mapping[str, object] | None = None,
) -> SuspectedVibrationOrigin:
    """Project a domain finding's origin into the canonical boundary payload shape."""
    fallback_payload = dict(fallback) if isinstance(fallback, Mapping) else {}

    origin = finding.origin
    hotspot = finding.location
    fallback_location = str(fallback_payload.get("location") or "").strip()
    if origin is None and hotspot is None:
        return fallback_payload
    if hotspot is None and fallback_location and fallback_location.lower() != "unknown":
        return fallback_payload

    return {
        "location": (
            origin.projected_location
            if origin is not None
            else str(finding.strongest_location or "unknown")
        ),
        "alternative_locations": (
            list(origin.alternative_locations)
            if origin is not None
            else list(hotspot.supporting_locations) if hotspot is not None else []
        ),
        "suspected_source": str(
            origin.suspected_source if origin is not None else finding.suspected_source
        ),
        "dominance_ratio": (
            origin.dominance_ratio if origin is not None else finding.dominance_ratio
        ),
        "weak_spatial_separation": (
            origin.weak_spatial_separation
            if origin is not None
            else finding.weak_spatial_separation
        ),
        "speed_band": origin.speed_band if origin is not None else finding.strongest_speed_band,
        "dominant_phase": origin.dominant_phase if origin is not None else None,
        "explanation": origin.explanation if origin is not None else "",
    }