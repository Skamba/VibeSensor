"""Canonical boundary codec for Finding payload encode/decode."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
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
from vibesensor.shared.types.finding_payload_parts import (
    FindingCorePayload,
    FindingPresentationPayload,
)
from vibesensor.shared.types.history_analysis_contracts import AmplitudeMetric, FindingPayload

__all__ = ["finding_from_payload", "finding_payload_from_domain"]

_MAX_SIGNATURES_PER_FINDING: int = 3

type _FindingProjector = Callable[[Finding], object]
type _PayloadDecoder = Callable[[Mapping[str, object]], object]
type _IncludePredicate = Callable[[object], bool]


def _always_include(_value: object) -> bool:
    return True


def _include_if_not_none(value: object) -> bool:
    return value is not None


def _include_if_text(value: object) -> bool:
    return value is not None and bool(str(value).strip())


def _include_if_truthy(value: object) -> bool:
    return bool(value)


@dataclass(frozen=True, slots=True)
class _FindingDomainFieldSpec:
    payload_key: str
    state_field: str
    project: _FindingProjector
    decode: _PayloadDecoder
    include: _IncludePredicate = _always_include


@dataclass(frozen=True, slots=True)
class _FindingPayloadFieldSpec:
    payload_key: str
    project: _FindingProjector
    include: _IncludePredicate = _always_include


type _FindingPayloadSpec = _FindingDomainFieldSpec | _FindingPayloadFieldSpec


@dataclass(frozen=True, slots=True)
class _DirectFindingPayloadState:
    finding_id: str
    finding_key: str
    confidence: float | None
    frequency_hz: float | None
    severity: str
    order: str
    strongest_location: str | None
    strongest_speed_band: str | None
    dominant_phase: str | None
    dominance_ratio: float | None
    weak_spatial_separation: bool
    diffuse_excitation: bool
    ranking_score: float
    peak_classification: str


def _project_finding_attribute(attr_name: str) -> _FindingProjector:
    def project(finding: Finding) -> object:
        return getattr(finding, attr_name)

    return project


def _finding_domain_field(
    payload_key: str,
    *,
    decode: _PayloadDecoder,
    state_field: str | None = None,
    attr_name: str | None = None,
    include: _IncludePredicate = _always_include,
) -> _FindingDomainFieldSpec:
    resolved_state_field = state_field or payload_key
    resolved_attr_name = attr_name or resolved_state_field
    return _FindingDomainFieldSpec(
        payload_key=payload_key,
        state_field=resolved_state_field,
        project=_project_finding_attribute(resolved_attr_name),
        decode=decode,
        include=include,
    )


def _payload_text_decoder(payload_key: str) -> _PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        return _text(payload.get(payload_key))

    return decode


def _payload_optional_text_decoder(payload_key: str) -> _PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        return _text(payload.get(payload_key)) or None

    return decode


def _payload_float_decoder(payload_key: str) -> _PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        return _as_float(payload.get(payload_key))

    return decode


def _payload_float_or_zero_decoder(payload_key: str) -> _PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        return _as_float(payload.get(payload_key)) or 0.0

    return decode


def _payload_bool_decoder(payload_key: str) -> _PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        return bool(payload.get(payload_key, False))

    return decode


def _project_dominant_phase(finding: Finding) -> object:
    if finding.origin is not None and finding.origin.dominant_phase is not None:
        return finding.origin.dominant_phase
    return finding.dominant_phase


def _project_peak_classification(finding: Finding) -> object:
    return finding.peaks.classification


def _project_suspected_source(finding: Finding) -> object:
    return str(finding.suspected_source)


def _project_finding_kind(finding: Finding) -> object:
    if finding.kind is None:
        return None
    return str(finding.kind)


def _project_signatures_observed(finding: Finding) -> object:
    return list(finding.signature_labels)


def _project_evidence_summary(finding: Finding) -> object:
    if finding.origin is None:
        return ""
    return finding.origin.reason


def _project_frequency_hz_or_order(finding: Finding) -> object:
    if finding.frequency_hz is not None:
        return finding.frequency_hz
    return finding.order or ""


def _project_confidence_assessment_field(attr_name: str) -> _FindingProjector:
    def project(finding: Finding) -> object:
        if finding.confidence_assessment is None:
            return None
        return getattr(finding.confidence_assessment, attr_name)

    return project


def _amplitude_metric_payload(finding: Finding) -> AmplitudeMetric:
    """Project the canonical presentation-only amplitude summary for a finding."""

    return {
        "name": "vibration_strength_db",
        "value": finding.vibration_strength_db,
        "units": "dB",
        "definition": payload_value_from_json(i18n_ref("METRIC_VIBRATION_STRENGTH_DB")),
    }


_DIRECT_FINDING_FIELD_SPECS: tuple[_FindingDomainFieldSpec, ...] = (
    _finding_domain_field("finding_id", decode=_payload_text_decoder("finding_id")),
    _finding_domain_field("finding_key", decode=_payload_text_decoder("finding_key")),
    _finding_domain_field("confidence", decode=_payload_float_decoder("confidence")),
    _finding_domain_field(
        "frequency_hz",
        decode=_payload_float_decoder("frequency_hz"),
        include=_include_if_not_none,
    ),
    _finding_domain_field(
        "severity",
        decode=_payload_text_decoder("severity"),
        include=_include_if_text,
    ),
    _finding_domain_field(
        "order",
        decode=_payload_text_decoder("order"),
        include=_include_if_text,
    ),
    _finding_domain_field(
        "strongest_location",
        decode=_payload_optional_text_decoder("strongest_location"),
    ),
    _finding_domain_field(
        "strongest_speed_band",
        decode=_payload_optional_text_decoder("strongest_speed_band"),
    ),
    _FindingDomainFieldSpec(
        payload_key="dominant_phase",
        state_field="dominant_phase",
        project=_project_dominant_phase,
        decode=_payload_optional_text_decoder("dominant_phase"),
        include=_include_if_text,
    ),
    _finding_domain_field("dominance_ratio", decode=_payload_float_decoder("dominance_ratio")),
    _finding_domain_field(
        "weak_spatial_separation",
        decode=_payload_bool_decoder("weak_spatial_separation"),
    ),
    _finding_domain_field(
        "diffuse_excitation",
        decode=_payload_bool_decoder("diffuse_excitation"),
    ),
    _finding_domain_field(
        "ranking_score",
        decode=_payload_float_or_zero_decoder("ranking_score"),
    ),
    _FindingDomainFieldSpec(
        payload_key="peak_classification",
        state_field="peak_classification",
        project=_project_peak_classification,
        decode=_payload_text_decoder("peak_classification"),
    ),
)
_CORE_ENCODE_ONLY_FIELD_SPECS: tuple[_FindingPayloadFieldSpec, ...] = (
    _FindingPayloadFieldSpec("suspected_source", _project_suspected_source),
    _FindingPayloadFieldSpec(
        "finding_kind",
        _project_finding_kind,
        include=_include_if_not_none,
    ),
    _FindingPayloadFieldSpec(
        "signatures_observed",
        _project_signatures_observed,
        include=_include_if_truthy,
    ),
)
_PRESENTATION_FIELD_SPECS: tuple[_FindingPayloadFieldSpec, ...] = (
    _FindingPayloadFieldSpec("evidence_summary", _project_evidence_summary),
    _FindingPayloadFieldSpec("frequency_hz_or_order", _project_frequency_hz_or_order),
    _FindingPayloadFieldSpec("amplitude_metric", _amplitude_metric_payload),
    _FindingPayloadFieldSpec(
        "confidence_label_key",
        _project_confidence_assessment_field("label_key"),
        include=_include_if_not_none,
    ),
    _FindingPayloadFieldSpec(
        "confidence_reason",
        _project_confidence_assessment_field("reason"),
        include=_include_if_not_none,
    ),
    _FindingPayloadFieldSpec(
        "confidence_tone",
        _project_confidence_assessment_field("tone"),
        include=_include_if_not_none,
    ),
    _FindingPayloadFieldSpec(
        "confidence_pct",
        _project_confidence_assessment_field("pct_text"),
        include=_include_if_not_none,
    ),
)
_DIRECT_FINDING_STATE_FACTORY: Callable[..., _DirectFindingPayloadState] = (
    _DirectFindingPayloadState
)


def _project_payload_fields(
    finding: Finding,
    specs: tuple[_FindingPayloadSpec, ...],
) -> dict[str, object]:
    payload: dict[str, object] = {}
    for spec in specs:
        value = spec.project(finding)
        if spec.include(value):
            payload[spec.payload_key] = value
    return payload


def _direct_finding_state_from_payload(
    payload: Mapping[str, object],
) -> _DirectFindingPayloadState:
    decoded_values = {
        spec.state_field: spec.decode(payload) for spec in _DIRECT_FINDING_FIELD_SPECS
    }
    return _DIRECT_FINDING_STATE_FACTORY(**decoded_values)


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


def _finding_core_payload_from_domain(finding: Finding) -> FindingCorePayload:
    """Project only the domain-owned finding fields."""

    payload = cast(
        FindingCorePayload,
        _project_payload_fields(
            finding,
            _DIRECT_FINDING_FIELD_SPECS + _CORE_ENCODE_ONLY_FIELD_SPECS,
        ),
    )

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

    return payload


def _finding_presentation_payload_from_domain(
    finding: Finding,
) -> FindingPresentationPayload:
    """Project rendering- and report-oriented finding metadata."""

    return cast(
        FindingPresentationPayload,
        _project_payload_fields(finding, _PRESENTATION_FIELD_SPECS),
    )


def finding_payload_from_domain(
    finding: Finding,
) -> FindingPayload:
    """Compose the persisted/public finding payload from core and presentation parts."""

    core_payload = _finding_core_payload_from_domain(finding)
    presentation_payload = _finding_presentation_payload_from_domain(finding)
    return cast(FindingPayload, {**core_payload, **presentation_payload})


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

    direct_fields = _direct_finding_state_from_payload(payload)
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
        dominance_ratio=direct_fields.dominance_ratio,
        speed_band=direct_fields.strongest_speed_band,
    )
    source = origin.suspected_source

    explicit_kind = payload.get("finding_kind")
    kind = Finding.derive_kind_from_fields(
        direct_fields.finding_id,
        direct_fields.severity,
        explicit_kind=str(explicit_kind) if isinstance(explicit_kind, str) else None,
    )

    return Finding(
        finding_id=direct_fields.finding_id,
        finding_key=direct_fields.finding_key,
        suspected_source=source,
        confidence=direct_fields.confidence,
        frequency_hz=direct_fields.frequency_hz,
        order=direct_fields.order,
        severity=direct_fields.severity,
        strongest_location=direct_fields.strongest_location,
        strongest_speed_band=direct_fields.strongest_speed_band,
        peak_classification=direct_fields.peak_classification,
        kind=kind,
        dominant_phase=direct_fields.dominant_phase,
        ranking_score=direct_fields.ranking_score,
        dominance_ratio=direct_fields.dominance_ratio,
        diffuse_excitation=direct_fields.diffuse_excitation,
        weak_spatial_separation=direct_fields.weak_spatial_separation,
        vibration_strength_db=(evidence.vibration_strength_db if evidence is not None else None),
        cruise_fraction=cruise_fraction,
        phases_detected=phases_detected,
        matched_points=matched_points,
        evidence=evidence,
        location=location,
        confidence_assessment=_confidence_assessment_from_payload(
            payload,
            confidence=direct_fields.confidence,
            weak_spatial_separation=direct_fields.weak_spatial_separation,
        ),
        origin=origin,
        signatures=_signatures_from_payload(
            payload,
            support_score=direct_fields.confidence or 0.0,
            source=source,
        ),
    )
