"""Encode domain Finding objects into persisted Finding payloads."""

from __future__ import annotations

from typing import cast

from vibesensor.domain import Finding
from vibesensor.domain.order_match import OrderMatchObservation
from vibesensor.shared.boundaries.analysis_payload import (
    AmplitudeMetric,
    FindingEvidenceMetrics,
    LocationHotspotPayload,
    MatchedPoint,
    PhaseEvidence,
)
from vibesensor.shared.json_utils import i18n_ref, payload_value_from_json
from vibesensor.shared.types.finding_payload_parts import (
    FindingCorePayload,
    FindingPresentationPayload,
)
from vibesensor.shared.types.history_analysis_contracts import FindingPayload


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


def _amplitude_metric_payload(finding: Finding) -> AmplitudeMetric:
    """Project the canonical presentation-only amplitude summary for a finding."""
    return {
        "name": "vibration_strength_db",
        "value": finding.vibration_strength_db,
        "units": "dB",
        "definition": payload_value_from_json(i18n_ref("METRIC_VIBRATION_STRENGTH_DB")),
    }


def _finding_core_payload_from_domain(finding: Finding) -> FindingCorePayload:
    """Project only the domain-owned finding fields."""
    payload: FindingCorePayload = {
        "finding_id": finding.finding_id,
        "finding_key": finding.finding_key,
        "suspected_source": str(finding.suspected_source),
        "confidence": finding.confidence,
        "strongest_location": finding.strongest_location,
        "strongest_speed_band": finding.strongest_speed_band,
        "weak_spatial_separation": finding.weak_spatial_separation,
        "dominance_ratio": finding.dominance_ratio,
        "diffuse_excitation": finding.diffuse_excitation,
        "ranking_score": finding.ranking_score,
        "peak_classification": finding.peaks.classification,
        "signatures_observed": list(finding.signature_labels),
    }
    if finding.severity:
        payload["severity"] = finding.severity
    if finding.kind is not None:
        payload["finding_kind"] = str(finding.kind)
    if finding.order:
        payload["order"] = finding.order
    if finding.dominant_phase:
        payload["dominant_phase"] = finding.dominant_phase
    if finding.matched_points:
        payload["matched_points"] = [
            matched_point_from_observation(point) for point in finding.matched_points
        ]

    if finding.evidence is not None:
        ev = finding.evidence
        metrics: FindingEvidenceMetrics = {
            "match_rate": ev.match_rate,
            "presence_ratio": ev.presence_ratio,
            "burstiness": ev.burstiness,
            "spatial_concentration": ev.spatial_concentration,
            "frequency_correlation": ev.frequency_correlation,
            "speed_uniformity": ev.speed_uniformity,
            "spatial_uniformity": ev.spatial_uniformity,
        }
        if ev.global_match_rate is not None:
            metrics["global_match_rate"] = ev.global_match_rate
        if ev.focused_speed_band is not None:
            metrics["focused_speed_band"] = ev.focused_speed_band
        if ev.mean_relative_error is not None:
            metrics["mean_relative_error"] = ev.mean_relative_error
        if ev.mean_noise_floor_db is not None:
            metrics["mean_noise_floor_db"] = ev.mean_noise_floor_db
        if ev.possible_samples is not None:
            metrics["possible_samples"] = ev.possible_samples
        if ev.matched_samples is not None:
            metrics["matched_samples"] = ev.matched_samples
        if ev.snr_db is not None:
            metrics["snr_db"] = ev.snr_db
        if ev.vibration_strength_db is not None:
            metrics["vibration_strength_db"] = ev.vibration_strength_db
        elif finding.vibration_strength_db is not None:
            metrics["vibration_strength_db"] = finding.vibration_strength_db
        if ev.phases_with_evidence is not None:
            metrics["phases_with_evidence"] = ev.phases_with_evidence
        if ev.phase_confidences:
            metrics["per_phase_confidence"] = dict(ev.phase_confidences)
        payload["evidence_metrics"] = metrics
    elif finding.vibration_strength_db is not None:
        payload["evidence_metrics"] = {"vibration_strength_db": finding.vibration_strength_db}

    if finding.cruise_fraction > 0.0 or finding.phases_detected:
        phase_evidence: PhaseEvidence = {"cruise_fraction": finding.cruise_fraction}
        if finding.phases_detected:
            phase_evidence["phases_detected"] = list(finding.phases_detected)
        payload["phase_evidence"] = phase_evidence

    if finding.location is not None:
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
        payload["location_hotspot"] = hotspot

    if finding.origin is not None and finding.origin.dominant_phase is not None:
        payload["dominant_phase"] = finding.origin.dominant_phase

    return payload


def _finding_presentation_payload_from_domain(
    finding: Finding,
) -> FindingPresentationPayload:
    """Project rendering- and report-oriented finding metadata."""
    payload: FindingPresentationPayload = {
        "evidence_summary": "",
        "frequency_hz_or_order": (
            finding.frequency_hz if finding.frequency_hz is not None else finding.order or ""
        ),
        "amplitude_metric": _amplitude_metric_payload(finding),
    }
    if finding.confidence_assessment is not None:
        ca = finding.confidence_assessment
        payload["confidence_label_key"] = ca.label_key
        payload["confidence_tone"] = ca.tone
        payload["confidence_pct"] = ca.pct_text
    if finding.origin is not None:
        payload["evidence_summary"] = finding.origin.reason
    return payload


def finding_payload_from_domain(
    finding: Finding,
) -> FindingPayload:
    """Compose the persisted/public finding payload from core and presentation parts."""
    core_payload = _finding_core_payload_from_domain(finding)
    presentation_payload = _finding_presentation_payload_from_domain(finding)
    return cast(FindingPayload, {**core_payload, **presentation_payload})
