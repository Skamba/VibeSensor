"""Primary-origin enrichment helpers for reconstructed persisted summaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from vibesensor.domain import Finding, LocationHotspot, VibrationOrigin
from vibesensor.shared.json_utils import as_float_or_none as _as_float

__all__ = ["enrich_primary_origin_from_summary"]


def _matches_finding(candidate: Finding, target: Finding) -> bool:
    if candidate == target:
        return True
    if not (candidate.finding_id and candidate.finding_id == target.finding_id):
        return False
    return (
        candidate.finding_key == target.finding_key
        and candidate.strongest_location == target.strongest_location
        and candidate.strongest_speed_band == target.strongest_speed_band
        and candidate.frequency_hz == target.frequency_hz
        and candidate.order == target.order
        and candidate.suspected_source == target.suspected_source
    )


def _domain_origin_from_summary_payload(
    payload: Mapping[str, object],
    *,
    primary: Finding,
    domain_origin: VibrationOrigin | None,
) -> VibrationOrigin | None:
    raw_location = str(payload.get("location") or "").strip()
    if not raw_location or raw_location.lower() == "unknown":
        return None
    strongest_location = raw_location.split(" / ", maxsplit=1)[0].strip()
    if not strongest_location or strongest_location.lower() == "unknown":
        return None
    alternatives_raw = payload.get("alternative_locations")
    alternatives = (
        tuple(str(location).strip() for location in alternatives_raw if str(location).strip())
        if isinstance(alternatives_raw, list)
        else ()
    )
    dominance_ratio = (
        domain_origin.dominance_ratio
        if domain_origin is not None and domain_origin.dominance_ratio is not None
        else primary.dominance_ratio
    )
    if dominance_ratio is None:
        dominance_ratio = _as_float(payload.get("dominance_ratio"))
    hotspot = LocationHotspot.from_analysis_inputs(
        strongest_location=strongest_location,
        dominance_ratio=dominance_ratio,
        weak_spatial_separation=(
            (domain_origin.weak_spatial_separation if domain_origin is not None else False)
            or primary.weak_spatial_separation
            or bool(payload.get("weak_spatial_separation", False))
            or bool(alternatives)
        ),
        ambiguous=bool(alternatives),
        alternative_locations=alternatives,
    )
    return VibrationOrigin.from_analysis_inputs(
        suspected_source=(
            domain_origin.suspected_source
            if domain_origin is not None
            else primary.suspected_source
        ),
        hotspot=hotspot,
        dominance_ratio=dominance_ratio,
        speed_band=(
            domain_origin.speed_band
            if domain_origin is not None and domain_origin.speed_band is not None
            else primary.strongest_speed_band
            or (str(payload.get("speed_band") or "").strip() or None)
        ),
        dominant_phase=(
            domain_origin.dominant_phase
            if domain_origin is not None and domain_origin.dominant_phase is not None
            else primary.dominant_phase
            or (str(payload.get("dominant_phase") or "").strip() or None)
        ),
        reason=domain_origin.reason if domain_origin is not None else "",
    )


def enrich_primary_origin_from_summary(
    summary: Mapping[str, object],
    *,
    findings: tuple[Finding, ...],
    top_causes: tuple[Finding, ...],
) -> tuple[tuple[Finding, ...], tuple[Finding, ...]]:
    summary_origin = summary.get("most_likely_origin")
    if not isinstance(summary_origin, Mapping):
        return findings, top_causes
    primary = top_causes[0] if top_causes else next((f for f in findings if f.is_diagnostic), None)
    if primary is None:
        return findings, top_causes
    domain_origin = VibrationOrigin.from_finding(primary)
    if domain_origin is not None and domain_origin.has_sufficient_location:
        return findings, top_causes
    enriched_origin = _domain_origin_from_summary_payload(
        summary_origin,
        primary=primary,
        domain_origin=domain_origin,
    )
    if enriched_origin is None or enriched_origin.hotspot is None:
        return findings, top_causes
    enriched_primary = replace(
        primary,
        strongest_location=primary.strongest_location or enriched_origin.hotspot.strongest_location,
        dominant_phase=primary.dominant_phase or enriched_origin.dominant_phase,
        dominance_ratio=(
            primary.dominance_ratio
            if primary.dominance_ratio is not None
            else enriched_origin.dominance_ratio
        ),
        weak_spatial_separation=(
            primary.weak_spatial_separation or enriched_origin.weak_spatial_separation
        ),
        location=primary.location or enriched_origin.hotspot,
        origin=enriched_origin,
    )

    def _replace_matches(items: tuple[Finding, ...]) -> tuple[Finding, ...]:
        return tuple(
            enriched_primary if _matches_finding(item, primary) else item for item in items
        )

    return _replace_matches(findings), _replace_matches(top_causes)
