"""Canonical boundary codec for Finding payload encode/decode."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from vibesensor.domain import (
    ConfidenceAssessment,
    Finding,
    FindingEvidence,
    Signature,
    VibrationSource,
)
from vibesensor.domain.order_match import OrderMatchObservation
from vibesensor.shared.boundaries.codecs import finding_evidence_from_mapping
from vibesensor.shared.boundaries.summary_fields.evidence_metrics import build_evidence_metrics
from vibesensor.shared.boundaries.summary_fields.order_match import (
    order_match_observations_from_sequence,
)
from vibesensor.shared.boundaries.summary_fields.origin import (
    location_hotspot_from_payload,
    vibration_origin_from_payload,
)
from vibesensor.shared.json_utils import (
    as_float_or_none as _as_float,
)
from vibesensor.shared.json_utils import (
    i18n_ref,
    payload_value_from_json,
)
from vibesensor.shared.types.analysis_views import (
    LocationHotspotPayload,
    MatchedPoint,
    PhaseEvidence,
)
from vibesensor.shared.types.history_analysis_contracts import AmplitudeMetric, FindingPayload

__all__ = [
    "finding_from_payload",
    "finding_payload_from_domain",
    "matched_point_from_observation",
]

_MAX_SIGNATURES_PER_FINDING: int = 3


def _has_text(value: str | None) -> bool:
    return value is not None and bool(value.strip())


def _amplitude_metric_payload(finding: Finding) -> AmplitudeMetric:
    """Project the canonical presentation-only amplitude summary for a finding."""

    return {
        "name": "vibration_strength_db",
        "value": finding.vibration_strength_db,
        "units": "dB",
        "definition": payload_value_from_json(i18n_ref("METRIC_VIBRATION_STRENGTH_DB")),
    }


def _matched_points_payload(finding: Finding) -> list[MatchedPoint] | None:
    if not finding.matched_points:
        return None
    return [matched_point_from_observation(point) for point in finding.matched_points]


def _phase_evidence_payload(finding: Finding) -> PhaseEvidence | None:
    if finding.cruise_fraction <= 0.0 and not finding.phases_detected:
        return None
    phase_evidence: PhaseEvidence = {"cruise_fraction": finding.cruise_fraction}
    if finding.phases_detected:
        phase_evidence["phases_detected"] = list(finding.phases_detected)
    return phase_evidence


def _location_hotspot_payload(finding: Finding) -> LocationHotspotPayload | None:
    if finding.location is None:
        return None
    loc = finding.location
    hotspot: LocationHotspotPayload = {
        "top_location": loc.strongest_location,
        "dominance_ratio": loc.dominance_ratio,
        "localization_confidence": loc.localization_confidence,
        "weak_spatial_separation": loc.weak_spatial_separation,
        "ambiguous_location": loc.ambiguous,
    }
    if loc.alternative_locations:
        hotspot["ambiguous_locations"] = list(loc.alternative_locations)
    if loc.location_count is not None:
        hotspot["location_count"] = loc.location_count
    return hotspot


def matched_point_from_observation(obs: OrderMatchObservation) -> MatchedPoint:
    """Serialize a domain ``OrderMatchObservation`` to a boundary ``MatchedPoint`` dict."""

    return MatchedPoint(
        t_s=obs.t_s,
        speed_kmh=obs.speed_kmh,
        predicted_hz=obs.predicted_hz,
        matched_hz=obs.matched_hz,
        rel_error=obs.rel_error,
        amp=obs.amp,
        location=obs.location,
        phase=obs.phase,
    )


def finding_payload_from_domain(finding: Finding) -> FindingPayload:
    """Project a domain ``Finding`` into the persisted/public finding payload.

    Key insertion order is part of the persisted JSON shape and must stay stable.
    """

    payload: dict[str, object] = {
        "finding_id": finding.finding_id,
        "finding_key": finding.finding_key,
        "confidence": finding.confidence,
    }
    if finding.frequency_hz is not None:
        payload["frequency_hz"] = finding.frequency_hz
    if _has_text(finding.severity):
        payload["severity"] = finding.severity
    if _has_text(finding.order):
        payload["order"] = finding.order
    payload["strongest_location"] = finding.strongest_location
    payload["strongest_speed_band"] = finding.strongest_speed_band
    dominant_phase = (
        finding.origin.dominant_phase
        if finding.origin is not None and finding.origin.dominant_phase is not None
        else finding.dominant_phase
    )
    if _has_text(dominant_phase):
        payload["dominant_phase"] = dominant_phase
    payload["dominance_ratio"] = finding.dominance_ratio
    payload["weak_spatial_separation"] = finding.weak_spatial_separation
    payload["diffuse_excitation"] = finding.diffuse_excitation
    payload["ranking_score"] = finding.ranking_score
    payload["peak_classification"] = finding.peaks.classification
    payload["suspected_source"] = str(finding.suspected_source)
    if finding.kind is not None:
        payload["finding_kind"] = str(finding.kind)
    payload["signatures_observed"] = list(finding.signature_labels)

    matched_points = _matched_points_payload(finding)
    if matched_points is not None:
        payload["matched_points"] = matched_points
    evidence_metrics = build_evidence_metrics(finding)
    if evidence_metrics is not None:
        payload["evidence_metrics"] = evidence_metrics
    phase_evidence = _phase_evidence_payload(finding)
    if phase_evidence is not None:
        payload["phase_evidence"] = phase_evidence
    hotspot = _location_hotspot_payload(finding)
    if hotspot is not None:
        payload["location_hotspot"] = hotspot

    payload["evidence_summary"] = finding.origin.reason if finding.origin is not None else ""
    payload["frequency_hz_or_order"] = (
        finding.frequency_hz if finding.frequency_hz is not None else finding.order or ""
    )
    payload["amplitude_metric"] = _amplitude_metric_payload(finding)
    assessment = finding.confidence_assessment
    if assessment is not None:
        payload["confidence_label_key"] = assessment.label_key
        payload["confidence_reason"] = assessment.reason
        payload["confidence_tone"] = assessment.tone
        payload["confidence_pct"] = assessment.pct_text
    return cast(FindingPayload, payload)


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

    finding_id = _text(payload.get("finding_id"))
    severity = _text(payload.get("severity"))
    confidence = _as_float(payload.get("confidence"))
    dominance_ratio = _as_float(payload.get("dominance_ratio"))
    strongest_speed_band = _text(payload.get("strongest_speed_band")) or None
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

    origin = vibration_origin_from_payload(
        payload,
        hotspot=location,
        dominance_ratio=dominance_ratio,
        speed_band=strongest_speed_band,
    )
    source = origin.suspected_source

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
        ranking_score=_as_float(payload.get("ranking_score")) or 0.0,
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
