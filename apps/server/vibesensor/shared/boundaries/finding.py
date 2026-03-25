"""Boundary decoder and projector for domain Finding.

``finding_from_payload``  — payload → domain (history reconstruction and
analysis finalization).
``finding_payload_from_domain`` — domain → payload (persistence serialization).

Also includes boundary functions for finding sub-objects (evidence,
location hotspot, test steps) and the structured-step-content helper. The
encoder keeps an internal split between domain-owned finding fields and
presentation-only finding metadata before composing the public
``FindingPayload`` contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from typing_extensions import TypedDict

from vibesensor.domain import Finding, FindingEvidence, Signature, VibrationSource, coerce_float
from vibesensor.domain.order_match import OrderMatchObservation
from vibesensor.domain.test_plan import RecommendedAction, TestPlan
from vibesensor.shared.boundaries.analysis_payload import (
    AmplitudeMetric,
    FindingEvidenceMetrics,
    LocationHotspotPayload,
    MatchedPoint,
    PhaseEvidence,
    TestPlanStepPayload,
)
from vibesensor.shared.boundaries.vibration_origin import (
    location_hotspot_from_payload,
    vibration_origin_from_payload,
)
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.json_utils import i18n_ref, payload_value_from_json
from vibesensor.shared.types.history_analysis_contracts import FindingPayload

_MAX_SIGNATURES_PER_FINDING: int = 3


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


# ---------------------------------------------------------------------------
# Sub-object decoders (formerly in separate modules)
# ---------------------------------------------------------------------------


def _has_structured_step_content(steps: object) -> bool:
    if not isinstance(steps, list):
        return False
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        for key in ("what", "why", "confirm", "falsify"):
            value = step.get(key)
            if isinstance(value, (Mapping, list)):
                return True
    return False


def step_payload_from_action(action: RecommendedAction) -> TestPlanStepPayload:
    """Project one semantic action into the persisted TestStep shape."""
    return {
        "action_id": action.action_id,
        "what": action.instruction,
        "why": action.rationale,
        "confirm": action.confirmation_signal,
        "falsify": action.falsification_signal,
        "eta": action.estimated_duration,
    }


def step_payloads_from_plan(test_plan: TestPlan) -> list[TestPlanStepPayload]:
    """Project a semantic TestPlan into the persisted TestStep payload list."""
    return [step_payload_from_action(action) for action in test_plan.prioritized_actions]


def _amplitude_metric_payload(finding: Finding) -> AmplitudeMetric:
    """Project the canonical presentation-only amplitude summary for a finding."""
    return {
        "name": "vibration_strength_db",
        "value": finding.vibration_strength_db,
        "units": "dB",
        "definition": payload_value_from_json(i18n_ref("METRIC_VIBRATION_STRENGTH_DB")),
    }


class _FindingCorePayload(TypedDict, total=False):
    """Internal domain-owned finding payload fields.

    This is the core mechanical/diagnostic meaning that the boundary encoder
    persists and the decoder reconstructs back into ``Finding``.
    """

    finding_id: str
    finding_key: str | None
    suspected_source: str
    confidence: float | None
    finding_kind: str | None
    severity: str | None
    matched_points: list[MatchedPoint]
    location_hotspot: LocationHotspotPayload | None
    strongest_location: str | None
    strongest_speed_band: str | None
    dominant_phase: str | None
    dominance_ratio: float | None
    weak_spatial_separation: bool
    diffuse_excitation: bool
    phase_evidence: PhaseEvidence | None
    evidence_metrics: FindingEvidenceMetrics | None
    ranking_score: float | None
    peak_classification: str | None
    signatures_observed: list[str]
    order: str | None


class _FindingPresentationPayload(TypedDict, total=False):
    """Internal rendering-oriented finding metadata.

    These fields keep outward API/report payload behavior stable, but the
    domain decoder does not own most of them directly.
    """

    evidence_summary: str
    frequency_hz_or_order: float | str
    amplitude_metric: AmplitudeMetric
    confidence_label_key: str | None
    confidence_tone: str | None
    confidence_pct: str | None


# ---------------------------------------------------------------------------
# Finding decoder and projector
# ---------------------------------------------------------------------------


def finding_from_payload(payload: Mapping[str, object]) -> Finding:
    """Create a domain Finding from a ``FindingPayload`` dict.

    Used at two boundary points:

    * **history reconstruction** — decoding persisted summaries via
      ``test_run_from_summary()``.
    * **analysis finalization** — converting analysis-pipeline dicts into
      domain objects at the end of ``finalize_findings()``.

    Extracts the domain-owned fields plus the persisted public-field fallbacks
    still needed to reconstruct origin/order semantics, while ignoring pure
    presentation hints such as ``amplitude_metric`` and ``confidence_*``.

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
            # Non-numeric value like "1x wheel" — preserve as order label
            freq_or_order_label = str(freq_raw).strip()

    loc = payload.get("strongest_location")
    band = payload.get("strongest_speed_band")

    # Evidence / ranking fields
    ranking_score = _as_float(payload.get("ranking_score")) or 0.0
    dominance_ratio = _as_float(payload.get("dominance_ratio"))

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

    # Extract vibration_strength_db from evidence_metrics
    vib_db: float | None = None
    ev_metrics = payload.get("evidence_metrics")
    if isinstance(ev_metrics, dict):
        vib_db = _as_float(ev_metrics.get("vibration_strength_db"))

    # Build domain value objects from nested dicts when available
    evidence: FindingEvidence | None = None
    if isinstance(ev_metrics, dict):
        evidence = FindingEvidence.from_metrics(ev_metrics)
    raw_matched_points = payload.get("matched_points")
    matched_points: tuple[OrderMatchObservation, ...] = ()
    if isinstance(raw_matched_points, list):
        matched_points = tuple(
            OrderMatchObservation.from_dict(point)
            for point in raw_matched_points
            if isinstance(point, Mapping)
        )
    hotspot_raw = payload.get("location_hotspot")
    location = location_hotspot_from_payload(hotspot_raw) if isinstance(hotspot_raw, dict) else None

    finding_id = _str("finding_id")
    severity = _str("severity")
    raw_source = _str("suspected_source").strip().lower()
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
        dominant_phase=_str("dominant_phase") or None,
        ranking_score=ranking_score,
        dominance_ratio=dominance_ratio,
        diffuse_excitation=bool(payload.get("diffuse_excitation", False)),
        weak_spatial_separation=bool(payload.get("weak_spatial_separation", False)),
        vibration_strength_db=vib_db,
        cruise_fraction=cruise_fraction,
        phases_detected=phases_detected,
        matched_points=matched_points,
        evidence=evidence,
        location=location,
        origin=origin,
        signatures=signatures,
    )


def _finding_core_payload_from_domain(finding: Finding) -> _FindingCorePayload:
    """Project only the domain-owned finding fields."""
    payload: _FindingCorePayload = {
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
) -> _FindingPresentationPayload:
    """Project rendering- and report-oriented finding metadata."""
    payload: _FindingPresentationPayload = {
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
    """Project a domain Finding to the current persisted/public payload dict.

    Produces the documented ``FindingPayload`` contract from domain objects
    alone, without pass-through shortcuts to original payload dicts.
    """
    core_payload = _finding_core_payload_from_domain(finding)
    presentation_payload = _finding_presentation_payload_from_domain(finding)
    return cast(FindingPayload, {**core_payload, **presentation_payload})
