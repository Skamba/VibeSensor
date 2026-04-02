"""Decode persisted Finding payloads back into domain Finding objects."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain import (
    ConfidenceAssessment,
    Finding,
    FindingEvidence,
    Signature,
    coerce_float,
)
from vibesensor.shared.boundaries.order_match_codec import order_match_observations_from_sequence
from vibesensor.shared.boundaries.vibration_origin import (
    location_hotspot_from_payload,
    vibration_origin_from_payload,
)
from vibesensor.shared.json_utils import as_float_or_none as _as_float

_MAX_SIGNATURES_PER_FINDING: int = 3


def finding_from_payload(payload: Mapping[str, object]) -> Finding:
    """Create a domain Finding from a ``FindingPayload`` dict.

    Used at two boundary points:

    * **history reconstruction** — decoding persisted summaries via
      ``test_run_from_summary()``.
    * **analysis finalization** — converting analysis-pipeline dicts into
      domain objects at the end of ``finalize_findings()``.

    Extracts the domain-owned fields plus the persisted public-field fallbacks
    still needed to reconstruct origin/order semantics. Pure presentation-only
    hints such as ``amplitude_metric`` are ignored, while serialized
    confidence-assessment fields are restored because downstream report and
    history consumers treat them as domain meaning.
    """

    def _str(key: str) -> str:
        v = payload.get(key)
        return str(v) if v is not None else ""

    confidence = _as_float(payload.get("confidence"))

    freq_raw = payload.get("frequency_hz") or payload.get("frequency_hz_or_order")
    frequency_hz: float | None = None
    freq_or_order_label: str = ""
    if freq_raw is not None:
        try:
            frequency_hz = coerce_float(freq_raw)
        except (TypeError, ValueError):
            freq_or_order_label = str(freq_raw).strip()

    loc = payload.get("strongest_location")
    band = payload.get("strongest_speed_band")

    ranking_score = _as_float(payload.get("ranking_score")) or 0.0
    dominance_ratio = _as_float(payload.get("dominance_ratio"))
    weak_spatial_separation = bool(payload.get("weak_spatial_separation", False))

    phase_ev = payload.get("phase_evidence")
    cruise_fraction = 0.0
    phases_detected: tuple[str, ...] = ()
    if isinstance(phase_ev, dict):
        cruise_fraction = _as_float(phase_ev.get("cruise_fraction")) or 0.0
        raw_phases_detected = phase_ev.get("phases_detected")
        if isinstance(raw_phases_detected, list):
            phases_detected = tuple(
                str(phase).strip() for phase in raw_phases_detected if str(phase).strip()
            )

    vib_db: float | None = None
    ev_metrics = payload.get("evidence_metrics")
    if isinstance(ev_metrics, dict):
        vib_db = _as_float(ev_metrics.get("vibration_strength_db"))

    evidence: FindingEvidence | None = None
    if isinstance(ev_metrics, dict):
        evidence = FindingEvidence.from_metrics(ev_metrics)
    raw_matched_points = payload.get("matched_points")
    matched_points = (
        order_match_observations_from_sequence(raw_matched_points)
        if isinstance(raw_matched_points, list)
        else ()
    )
    hotspot_raw = payload.get("location_hotspot")
    location = location_hotspot_from_payload(hotspot_raw) if isinstance(hotspot_raw, dict) else None

    finding_id = _str("finding_id")
    severity = _str("severity")
    origin = vibration_origin_from_payload(
        payload,
        hotspot=location,
        dominance_ratio=dominance_ratio,
        speed_band=str(band) if band is not None else None,
    )
    source = origin.suspected_source

    explicit = payload.get("finding_kind")
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
            for label in raw_signatures[:_MAX_SIGNATURES_PER_FINDING]
            if str(label).strip()
        )
        if isinstance(raw_signatures, list)
        else ()
    )
    label_key = payload.get("confidence_label_key")
    tone = payload.get("confidence_tone")
    pct_text = payload.get("confidence_pct")
    confidence_assessment = (
        ConfidenceAssessment(
            raw_confidence=confidence or 0.0,
            label_key=label_key,
            tone=tone,
            pct_text=pct_text,
            reason=str(payload.get("confidence_reason") or ""),
            weak_spatial=weak_spatial_separation,
        )
        if isinstance(label_key, str) and isinstance(tone, str) and isinstance(pct_text, str)
        else None
    )
    return Finding(
        finding_id=finding_id,
        finding_key=_str("finding_key"),
        suspected_source=source,
        confidence=confidence,
        frequency_hz=frequency_hz,
        order=_str("order") or freq_or_order_label,
        severity=severity,
        strongest_location=str(loc) if loc is not None else None,
        strongest_speed_band=str(band) if band is not None else None,
        peak_classification=_str("peak_classification"),
        kind=kind,
        dominant_phase=_str("dominant_phase") or None,
        ranking_score=ranking_score,
        dominance_ratio=dominance_ratio,
        diffuse_excitation=bool(payload.get("diffuse_excitation", False)),
        weak_spatial_separation=weak_spatial_separation,
        vibration_strength_db=vib_db,
        cruise_fraction=cruise_fraction,
        phases_detected=phases_detected,
        matched_points=matched_points,
        evidence=evidence,
        location=location,
        confidence_assessment=confidence_assessment,
        origin=origin,
        signatures=signatures,
    )
