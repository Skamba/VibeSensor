"""Boundary decoder and projector for domain Finding.

``finding_from_payload``  — payload → domain (history reconstruction and
analysis finalization).
``finding_payload_from_domain`` — domain → payload (persistence serialization).
"""

from __future__ import annotations

from collections.abc import Mapping

from ..domain.finding import Finding, VibrationSource
from ..domain.signature import Signature
from .finding_evidence import finding_evidence_from_metrics
from .location_hotspot import location_hotspot_from_payload
from .vibration_origin import vibration_origin_from_payload

_MAX_SIGNATURES_PER_FINDING: int = 3


def finding_from_payload(payload: Mapping[str, object]) -> Finding:
    """Create a domain Finding from a ``FindingPayload`` dict.

    Used at two boundary points:

    * **history reconstruction** — decoding persisted summaries via
      ``test_run_from_summary()``.
    * **analysis finalization** — converting analysis-pipeline dicts into
      domain objects at the end of ``finalize_findings()``.

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
    freq_or_order_label: str = ""
    if freq_raw is not None:
        try:
            frequency_hz = float(freq_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            # Non-numeric value like "1x wheel" — preserve as order label
            freq_or_order_label = str(freq_raw).strip()

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
    evidence = finding_evidence_from_metrics(ev_metrics) if isinstance(ev_metrics, dict) else None
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
            for label in raw_signatures[:_MAX_SIGNATURES_PER_FINDING]
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
) -> dict[str, object]:
    """Project a domain Finding to a complete payload dict.

    Produces all FindingPayload fields from domain objects alone,
    without pass-through shortcuts to original payload dicts.
    """
    payload: dict[str, object] = {
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
        "peak_classification": finding.peak_classification,
        "signatures_observed": list(finding.signature_labels),
        "evidence_summary": "",
        "frequency_hz_or_order": (
            finding.frequency_hz if finding.frequency_hz is not None else finding.order or ""
        ),
        "amplitude_metric": {"vibration_strength_db": finding.vibration_strength_db},
        "quick_checks": [],
    }
    if finding.severity:
        payload["severity"] = finding.severity
    if finding.kind is not None:
        payload["finding_kind"] = str(finding.kind)
    if finding.order:
        payload["order"] = finding.order

    # Evidence metrics
    if finding.evidence is not None:
        ev = finding.evidence
        metrics: dict[str, object] = {
            "match_rate": ev.match_rate,
            "presence_ratio": ev.presence_ratio,
            "burstiness": ev.burstiness,
            "spatial_concentration": ev.spatial_concentration,
            "frequency_correlation": ev.frequency_correlation,
            "speed_uniformity": ev.speed_uniformity,
            "spatial_uniformity": ev.spatial_uniformity,
        }
        if ev.snr_db is not None:
            metrics["snr_db"] = ev.snr_db
        if ev.vibration_strength_db is not None:
            metrics["vibration_strength_db"] = ev.vibration_strength_db
        if ev.phase_confidences:
            metrics["per_phase_confidence"] = dict(ev.phase_confidences)
        payload["evidence_metrics"] = metrics
    elif finding.vibration_strength_db is not None:
        payload["evidence_metrics"] = {"vibration_strength_db": finding.vibration_strength_db}

    # Phase evidence
    if finding.cruise_fraction > 0.0:
        payload["phase_evidence"] = {"cruise_fraction": finding.cruise_fraction}

    # Location hotspot
    if finding.location is not None:
        loc = finding.location
        hotspot: dict[str, object] = {
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

    # Confidence assessment
    if finding.confidence_assessment is not None:
        ca = finding.confidence_assessment
        payload["confidence_label_key"] = ca.label_key
        payload["confidence_tone"] = ca.tone
        payload["confidence_pct"] = ca.pct_text

    # Origin / evidence summary
    if finding.origin is not None:
        payload["evidence_summary"] = finding.origin.reason
        if finding.origin.dominant_phase is not None:
            payload["dominant_phase"] = finding.origin.dominant_phase

    return payload
