"""Boundary decoder: payload dict → domain Finding."""

from __future__ import annotations

from collections.abc import Mapping

from ..domain.finding import Finding, VibrationSource
from ..domain.finding_evidence import FindingEvidence
from ..domain.signature import Signature
from .location_hotspot import location_hotspot_from_payload
from .vibration_origin import vibration_origin_from_payload


def finding_from_payload(payload: Mapping[str, object]) -> Finding:
    """Create a domain Finding from a ``FindingPayload`` dict.

    Extracts the subset of fields that the domain object cares about,
    ignoring serialization-only keys present in the full payload.

    Reads ``suspected_source`` with fallback to ``source`` for backward
    compatibility with legacy dicts that used the ``source`` key.
    """

    def _str(key: str, *fallback_keys: str) -> str:
        v = payload.get(key)
        if v is None:
            for fk in fallback_keys:
                v = payload.get(fk)
                if v is not None:
                    break
        return str(v) if v is not None else ""

    conf_raw = payload.get("confidence")
    confidence: float | None = None
    if conf_raw is not None:
        try:
            confidence = float(conf_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pass

    freq_raw = payload.get("frequency_hz") or payload.get("frequency_hz_or_order")
    frequency_hz: float | None = None
    if freq_raw is not None:
        try:
            frequency_hz = float(freq_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pass

    loc = payload.get("strongest_location")
    band = payload.get("strongest_speed_band")

    # Evidence / ranking fields
    ranking_raw = payload.get("ranking_score")
    ranking_score = 0.0
    if ranking_raw is not None:
        try:
            ranking_score = float(ranking_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pass

    dominance_raw = payload.get("dominance_ratio")
    dominance_ratio: float | None = None
    if dominance_raw is not None:
        try:
            dominance_ratio = float(dominance_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pass

    phase_ev = payload.get("phase_evidence")
    cruise_fraction = 0.0
    if isinstance(phase_ev, dict):
        try:
            cruise_fraction = float(phase_ev.get("cruise_fraction", 0.0))
        except (TypeError, ValueError):
            pass

    # Extract vibration_strength_db from evidence_metrics
    vib_db: float | None = None
    ev_metrics = payload.get("evidence_metrics")
    if isinstance(ev_metrics, dict):
        raw_db = ev_metrics.get("vibration_strength_db")
        if raw_db is not None:
            try:
                vib_db = float(raw_db)
            except (TypeError, ValueError):
                pass

    # Build domain value objects from nested dicts when available
    evidence = (
        FindingEvidence.from_metrics_dict(ev_metrics) if isinstance(ev_metrics, dict) else None
    )
    hotspot_raw = payload.get("location_hotspot")
    location = location_hotspot_from_payload(hotspot_raw) if isinstance(hotspot_raw, dict) else None

    finding_id = _str("finding_id")
    severity = _str("severity")
    raw_source = _str("suspected_source", "source").strip().lower()
    try:
        source = VibrationSource(raw_source)
    except ValueError:
        source = VibrationSource.UNKNOWN

    # Derive kind from explicit finding_type or infer from fields
    explicit = payload.get("finding_kind") or payload.get("finding_type")
    kind = Finding.derive_kind_from_fields(
        finding_id,
        severity,
        explicit_kind=str(explicit) if isinstance(explicit, str) else None,
    )
    raw_signatures = payload.get("signatures_observed")
    signatures = (
        tuple(
            Signature.from_label(
                str(label),
                source=source,
                support_score=confidence or 0.0,
            )
            for label in raw_signatures[:3]
            if str(label).strip()
        )
        if isinstance(raw_signatures, list)
        else ()
    )
    origin = vibration_origin_from_payload(
        payload,
        hotspot=location,
        suspected_source=source,
        dominance_ratio=dominance_ratio,
        speed_band=str(band) if band is not None else None,
    )

    return Finding(
        finding_id=finding_id,
        suspected_source=source,
        confidence=confidence,
        frequency_hz=frequency_hz,
        order=_str("order"),
        severity=severity,
        strongest_location=str(loc) if loc is not None else None,
        strongest_speed_band=str(band) if band is not None else None,
        peak_classification=_str("peak_classification"),
        kind=kind,
        ranking_score=ranking_score,
        dominance_ratio=dominance_ratio,
        diffuse_excitation=bool(payload.get("diffuse_excitation", False)),
        weak_spatial_separation=bool(payload.get("weak_spatial_separation", False)),
        vibration_strength_db=vib_db,
        cruise_fraction=cruise_fraction,
        evidence=evidence,
        location=location,
        origin=origin,
        signatures=signatures,
    )


def finding_payload_from_domain(
    finding: Finding,
    *,
    primary: Mapping[str, Mapping[str, object]],
    secondary: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    """Project a domain Finding back to a payload dict.

    If the finding's ``finding_id`` matches a key in *primary* or
    *secondary*, the original payload dict is returned as-is (pass-through).
    Otherwise a minimal payload is synthesised from the domain object.
    """
    if finding.finding_id:
        payload = primary.get(finding.finding_id) or secondary.get(finding.finding_id)
        if payload is not None:
            return dict(payload)

    payload: dict[str, object] = {
        "finding_id": finding.finding_id,
        "suspected_source": str(finding.suspected_source),
        "confidence": finding.confidence,
        "strongest_location": finding.strongest_location,
        "strongest_speed_band": finding.strongest_speed_band,
        "weak_spatial_separation": finding.weak_spatial_separation,
        "dominance_ratio": finding.dominance_ratio,
        "signatures_observed": list(finding.signature_labels),
    }
    if finding.vibration_strength_db is not None:
        payload["evidence_metrics"] = {"vibration_strength_db": finding.vibration_strength_db}
    if finding.location is not None:
        payload["location_hotspot"] = {
            "best_location": finding.location.best_location,
            "alternative_locations": list(finding.location.alternative_locations),
            "dominance_ratio": finding.location.dominance_ratio,
            "weak_spatial_separation": not finding.location.is_well_localized,
        }
    if finding.origin is not None:
        payload["evidence_summary"] = finding.origin.reason
        if finding.origin.dominant_phase is not None:
            payload["dominant_phase"] = finding.origin.dominant_phase
    return payload
