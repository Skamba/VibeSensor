"""Boundary decoders for LocationHotspot payload shapes."""

from __future__ import annotations

from vibesensor.domain.location_hotspot import LocationHotspot

__all__ = ["location_hotspot_from_payload"]


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
