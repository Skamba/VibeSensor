"""Reconstruct domain Finding objects from canonical finding payloads."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain import (
    ConfidenceAssessment,
    Finding,
    FindingEvidence,
    Signature,
    VibrationSource,
)
from vibesensor.shared.boundaries.finding_evidence_codec import finding_evidence_from_mapping
from vibesensor.shared.boundaries.order_match_codec import order_match_observations_from_sequence
from vibesensor.shared.boundaries.vibration_origin import (
    location_hotspot_from_payload,
    vibration_origin_from_payload,
)
from vibesensor.shared.json_utils import as_float_or_none as _as_float

_MAX_SIGNATURES_PER_FINDING: int = 3


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _phase_evidence(payload: Mapping[str, object]) -> tuple[float, tuple[str, ...]]:
    phase_ev = payload.get("phase_evidence")
    if not isinstance(phase_ev, Mapping):
        return 0.0, ()
    raw_phases_detected = phase_ev.get("phases_detected")
    phases_detected = (
        tuple(str(phase).strip() for phase in raw_phases_detected if str(phase).strip())
        if isinstance(raw_phases_detected, list)
        else ()
    )
    return _as_float(phase_ev.get("cruise_fraction")) or 0.0, phases_detected


def _confidence_assessment_from_payload(
    payload: Mapping[str, object],
    *,
    confidence: float | None,
    weak_spatial_separation: bool,
) -> ConfidenceAssessment | None:
    label_key = payload.get("confidence_label_key")
    tone = payload.get("confidence_tone")
    pct_text = payload.get("confidence_pct")
    if not isinstance(label_key, str) or not isinstance(tone, str) or not isinstance(pct_text, str):
        return None
    return ConfidenceAssessment(
        raw_confidence=confidence or 0.0,
        label_key=label_key,
        tone=tone,
        pct_text=pct_text,
        reason=str(payload.get("confidence_reason") or ""),
        weak_spatial=weak_spatial_separation,
    )


def _signatures_from_payload(
    payload: Mapping[str, object],
    *,
    support_score: float,
    source: VibrationSource,
) -> tuple[Signature, ...]:
    raw_signatures = payload.get("signatures_observed")
    if not isinstance(raw_signatures, list):
        return ()
    return tuple(
        Signature.from_label(
            str(label),
            source=source,
            support_score=support_score,
        )
        for label in raw_signatures[:_MAX_SIGNATURES_PER_FINDING]
        if str(label).strip()
    )


def finding_from_payload(payload: Mapping[str, object]) -> Finding:
    """Create a domain Finding from the canonical finding payload shape."""

    confidence = _as_float(payload.get("confidence"))
    ranking_score = _as_float(payload.get("ranking_score")) or 0.0
    dominance_ratio = _as_float(payload.get("dominance_ratio"))
    weak_spatial_separation = bool(payload.get("weak_spatial_separation", False))
    cruise_fraction, phases_detected = _phase_evidence(payload)

    evidence_raw = payload.get("evidence_metrics")
    evidence: FindingEvidence | None = (
        finding_evidence_from_mapping(evidence_raw) if isinstance(evidence_raw, Mapping) else None
    )

    raw_matched_points = payload.get("matched_points")
    matched_points = (
        order_match_observations_from_sequence(raw_matched_points)
        if isinstance(raw_matched_points, list)
        else ()
    )

    hotspot_raw = payload.get("location_hotspot")
    location = (
        location_hotspot_from_payload(hotspot_raw) if isinstance(hotspot_raw, Mapping) else None
    )

    strongest_speed_band = _text(payload.get("strongest_speed_band")) or None
    origin = vibration_origin_from_payload(
        payload,
        hotspot=location,
        dominance_ratio=dominance_ratio,
        speed_band=strongest_speed_band,
    )
    source = origin.suspected_source

    finding_id = _text(payload.get("finding_id"))
    severity = _text(payload.get("severity"))
    explicit_kind = payload.get("finding_kind")
    kind = Finding.derive_kind_from_fields(
        finding_id,
        severity,
        explicit_kind=str(explicit_kind) if isinstance(explicit_kind, str) else None,
    )

    return Finding(
        finding_id=finding_id,
        finding_key=_text(payload.get("finding_key")),
        suspected_source=source,
        confidence=confidence,
        frequency_hz=_as_float(payload.get("frequency_hz")),
        order=_text(payload.get("order")),
        severity=severity,
        strongest_location=_text(payload.get("strongest_location")) or None,
        strongest_speed_band=strongest_speed_band,
        peak_classification=_text(payload.get("peak_classification")),
        kind=kind,
        dominant_phase=_text(payload.get("dominant_phase")) or None,
        ranking_score=ranking_score,
        dominance_ratio=dominance_ratio,
        diffuse_excitation=bool(payload.get("diffuse_excitation", False)),
        weak_spatial_separation=weak_spatial_separation,
        vibration_strength_db=(evidence.vibration_strength_db if evidence is not None else None),
        cruise_fraction=cruise_fraction,
        phases_detected=phases_detected,
        matched_points=matched_points,
        evidence=evidence,
        location=location,
        confidence_assessment=_confidence_assessment_from_payload(
            payload,
            confidence=confidence,
            weak_spatial_separation=weak_spatial_separation,
        ),
        origin=origin,
        signatures=_signatures_from_payload(
            payload,
            support_score=confidence or 0.0,
            source=source,
        ),
    )
