"""Boundary decoders and projectors for VibrationOrigin payload shapes."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain import Finding, VibrationSource
from vibesensor.domain.location_hotspot import LocationHotspot
from vibesensor.domain.vibration_origin import VibrationOrigin
from vibesensor.shared.constants.phases import PHASE_I18N_KEYS
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.json_utils import as_int_or_none as _as_int
from vibesensor.shared.json_utils import i18n_ref
from vibesensor.shared.types.history_analysis_contracts import (
    SuspectedVibrationOriginPayload as SuspectedVibrationOrigin,
)
from vibesensor.shared.types.json_types import JsonValue

_SOURCES_BY_VALUE: dict[str, VibrationSource] = {
    str(source.value): source for source in VibrationSource
}
_PHASE_ONSET_KEYS = frozenset({"acceleration", "deceleration", "coast_down"})


def location_hotspot_from_payload(payload: Mapping[str, object]) -> LocationHotspot:
    """Decode a persisted or transported hotspot payload into a domain object."""
    alts = payload.get("ambiguous_locations") or []
    if not isinstance(alts, (list, tuple)):
        alts = []
    alt_strings = [str(a) for a in alts if str(a).strip()]

    return LocationHotspot(
        strongest_location=str(payload.get("top_location") or ""),
        dominance_ratio=_as_float(payload.get("dominance_ratio")),
        localization_confidence=_as_float(payload.get("localization_confidence")),
        weak_spatial_separation=bool(payload.get("weak_spatial_separation", False)),
        ambiguous=bool(payload.get("ambiguous_location", False)),
        alternative_locations=tuple(alt_strings),
        location_count=_as_int(payload.get("location_count")),
    )


__all__ = [
    "SuspectedVibrationOrigin",
    "origin_payload_from_finding",
    "vibration_origin_from_payload",
]


def _source_from_payload(
    payload: Mapping[str, object],
) -> VibrationSource:
    """Resolve a suspected source from the canonical payload field."""
    raw_source = str(payload.get("suspected_source") or "").strip().lower()
    return _SOURCES_BY_VALUE.get(raw_source, VibrationSource.UNKNOWN)


def vibration_origin_from_payload(
    payload: Mapping[str, object],
    *,
    hotspot: LocationHotspot | None = None,
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
        raw_speed_band = payload.get("strongest_speed_band")
        if raw_speed_band is not None:
            normalized_speed_band = str(raw_speed_band).strip()
            resolved_speed_band = normalized_speed_band or None

    resolved_reason = payload.get("evidence_summary")
    reason = str(resolved_reason).strip() if isinstance(resolved_reason, str) else ""
    raw_dominant_phase = payload.get("dominant_phase")
    dominant_phase = None
    if raw_dominant_phase is not None:
        normalized_dominant_phase = str(raw_dominant_phase).strip()
        dominant_phase = normalized_dominant_phase or None

    return VibrationOrigin.from_analysis_inputs(
        suspected_source=_source_from_payload(payload),
        hotspot=resolved_hotspot,
        dominance_ratio=(
            dominance_ratio
            if dominance_ratio is not None
            else _as_float(payload.get("dominance_ratio"))
        ),
        speed_band=resolved_speed_band,
        dominant_phase=dominant_phase,
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


def build_origin_explanation(
    *,
    source: str,
    speed_band: str,
    location: str,
    dominance: float | None,
    weak: bool,
    dominant_phase: str,
) -> JsonValue:
    """Build the language-neutral origin explanation block."""
    explanation_parts: list[JsonValue] = [
        i18n_ref(
            "ORIGIN_EXPLANATION_FINDING_1",
            source=source,
            speed_band=speed_band or "unknown",
            location=location,
            dominance=f"{dominance:.2f}x" if dominance is not None else "n/a",
        ),
    ]
    if weak:
        explanation_parts.append(i18n_ref("WEAK_SPATIAL_SEPARATION_INSPECT_NEARBY"))
    if dominant_phase and dominant_phase in _PHASE_ONSET_KEYS and dominant_phase in PHASE_I18N_KEYS:
        explanation_parts.append(i18n_ref("ORIGIN_PHASE_ONSET_NOTE", phase=dominant_phase))
    return explanation_parts[0] if len(explanation_parts) == 1 else explanation_parts
