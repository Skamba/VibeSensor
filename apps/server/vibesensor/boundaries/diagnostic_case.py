"""Domain <-> summary boundary conversions for diagnostic cases and runs."""

from __future__ import annotations

from collections.abc import Mapping

from ..domain.car import Car
from ..domain.configuration_snapshot import ConfigurationSnapshot
from ..domain.diagnostic_case import DiagnosticCase
from ..domain.driving_phase import DrivingPhase
from ..domain.driving_segment import DrivingSegment
from ..domain.finding import Finding
from ..domain.hypothesis import Hypothesis, HypothesisStatus
from ..domain.recommended_action import RecommendedAction
from ..domain.run import Run
from ..domain.run_suitability import RunSuitability
from ..domain.signature import Signature
from ..domain.symptom import Symptom
from ..domain.test_plan import TestPlan
from ..domain.test_run import TestRun
from ._helpers import _as_float, _has_structured_step_content, _payloads_by_id
from .finding import finding_from_payload, finding_payload_from_domain
from .run_suitability import run_suitability_from_payload, run_suitability_payload
from .speed_profile import speed_profile_from_stats
from .test_steps import step_payloads_from_plan
from .vibration_origin import origin_payload_from_finding, vibration_origin_from_payload


def _actions_from_steps(steps: object) -> tuple[RecommendedAction, ...]:
    if not isinstance(steps, list):
        return ()
    actions: list[RecommendedAction] = []
    for idx, step in enumerate(steps):
        if not isinstance(step, Mapping):
            continue
        actions.append(
            RecommendedAction(
                action_id=str(step.get("action_id") or f"action-{idx + 1}"),
                what=str(step.get("what") or ""),
                why=str(step.get("why") or ""),
                confirm=str(step.get("confirm") or ""),
                falsify=str(step.get("falsify") or ""),
                eta=str(step.get("eta") or "") or None,
                priority=idx,
            )
        )
    return tuple(actions)


def _segments_from_summary(summary: Mapping[str, object]) -> tuple[DrivingSegment, ...]:
    raw_segments = summary.get("phase_segments")
    if not isinstance(raw_segments, list):
        return ()
    segments: list[DrivingSegment] = []
    for segment in raw_segments:
        if not isinstance(segment, Mapping):
            continue
        phase_raw = str(segment.get("phase") or "cruise").upper()
        try:
            phase = DrivingPhase[phase_raw]
        except KeyError:
            phase = DrivingPhase.CRUISE
        segments.append(
            DrivingSegment(
                phase=phase,
                start_idx=int(_as_float(segment.get("start_idx")) or 0),
                end_idx=int(_as_float(segment.get("end_idx")) or 0),
                start_t_s=_as_float(segment.get("start_t_s")),
                end_t_s=_as_float(segment.get("end_t_s")),
                speed_min_kmh=_as_float(segment.get("speed_min_kmh")),
                speed_max_kmh=_as_float(segment.get("speed_max_kmh")),
                sample_count=int(_as_float(segment.get("sample_count")) or 0),
            )
        )
    return tuple(segments)


def _signatures_from_finding(
    finding: Finding,
    payload: Mapping[str, object],
) -> tuple[Signature, ...]:
    raw_signatures = payload.get("signatures_observed")
    if not isinstance(raw_signatures, list):
        return ()
    return tuple(
        Signature.from_label(
            str(label),
            source=finding.suspected_source,
            support_score=finding.effective_confidence,
        )
        for label in raw_signatures[:3]
        if str(label).strip()
    )


def _hypothesis_from_finding(finding: Finding, signatures: tuple[Signature, ...]) -> Hypothesis:
    status = (
        HypothesisStatus.SUPPORTED
        if finding.effective_confidence >= Hypothesis.SUPPORTED_THRESHOLD
        else HypothesisStatus.INCONCLUSIVE
    )
    return Hypothesis(
        hypothesis_id=finding.finding_id or f"hyp-{finding.suspected_source}",
        source=finding.suspected_source,
        signature_keys=tuple(signature.key for signature in signatures),
        support_score=finding.effective_confidence,
        contradiction_score=0.0,
        status=status,
        rationale=(
            (finding.confidence_assessment.reason,)
            if finding.confidence_assessment and finding.confidence_assessment.reason
            else ()
        ),
    )



def _checks_from_suitability(suitability: RunSuitability | None) -> list[dict[str, object]]:
    return run_suitability_payload(suitability)


def _enrich_findings(raw_findings: object) -> tuple[Finding, ...]:
    if not isinstance(raw_findings, list):
        return ()
    enriched: list[Finding] = []
    for payload in raw_findings:
        if not isinstance(payload, Mapping):
            continue
        finding = finding_from_payload(payload)
        signatures = _signatures_from_finding(finding, payload)
        origin = vibration_origin_from_payload(
            payload,
            hotspot=finding.location,
            suspected_source=finding.suspected_source,
            dominance_ratio=finding.dominance_ratio,
            speed_band=finding.strongest_speed_band,
        )
        enriched.append(finding.with_origin_and_signatures(origin=origin, signatures=signatures))
    return tuple(enriched)


def _require_authoritative_case_id(summary: Mapping[str, object]) -> str:
    case_id = summary.get("case_id")
    if isinstance(case_id, str):
        normalized_case_id = case_id.strip()
        if normalized_case_id:
            return normalized_case_id
    raise ValueError(
        "Cannot decode DiagnosticCase from legacy summary without authoritative case_id"
    )


def _ensure_top_causes_in_findings(
    findings: tuple[Finding, ...],
    top_causes: tuple[Finding, ...],
) -> tuple[Finding, ...]:
    """Merge unmatched top_causes into findings so the domain invariant holds."""
    if not top_causes:
        return findings
    merged = list(findings)
    for tc in top_causes:
        if any(tc == f or (tc.finding_id and tc.finding_id == f.finding_id) for f in merged):
            continue
        merged.append(tc)
    return tuple(merged)


def test_run_from_summary(summary: Mapping[str, object]) -> TestRun:
    metadata = summary.get("metadata")
    meta = metadata if isinstance(metadata, Mapping) else {}
    findings = _enrich_findings(summary.get("findings"))
    top_causes = _enrich_findings(summary.get("top_causes"))
    # Domain invariant: top_causes ⊆ findings.  Payload data may have
    # top_causes that don't appear in findings; merge them so the
    # invariant holds without discarding data.
    findings = _ensure_top_causes_in_findings(findings, top_causes)
    actions = _actions_from_steps(summary.get("test_plan"))
    speed_stats = summary.get("speed_stats")
    phase_info = summary.get("phase_info")
    if not isinstance(phase_info, Mapping):
        phase_info = summary.get("phase_summary")
    speed_profile = (
        speed_profile_from_stats(
            speed_stats,
            phase_info if isinstance(phase_info, Mapping) else None,
        )
        if isinstance(speed_stats, Mapping)
        else None
    )
    run_suitability = summary.get("run_suitability")
    suitability = (
        run_suitability_from_payload(run_suitability) if isinstance(run_suitability, list) else None
    )

    signatures: list[Signature] = []
    hypotheses: list[Hypothesis] = []
    raw_findings = summary.get("findings") if isinstance(summary.get("findings"), list) else []
    for payload, finding in zip(raw_findings, findings, strict=False):
        if not isinstance(payload, Mapping):
            continue
        finding_signatures = _signatures_from_finding(finding, payload)
        signatures.extend(finding_signatures)
        hypotheses.append(_hypothesis_from_finding(finding, finding_signatures))

    return TestRun(
        run=Run(run_id=str(summary.get("run_id") or "unknown")),
        configuration_snapshot=ConfigurationSnapshot.from_metadata(meta),
        driving_segments=_segments_from_summary(summary),
        signatures=tuple(dict.fromkeys(signatures)),
        hypotheses=tuple(hypotheses),
        findings=findings,
        top_causes=top_causes,
        speed_profile=speed_profile,
        suitability=suitability,
        test_plan=TestPlan(
            actions=actions,
            requires_additional_data=not bool(findings),
        ),
    )


def diagnostic_case_from_summary(summary: Mapping[str, object]) -> DiagnosticCase:
    metadata = summary.get("metadata")
    meta = metadata if isinstance(metadata, Mapping) else {}
    car = Car(
        name=str(meta.get("car_name") or meta.get("name") or "Unnamed Car"),
        car_type=str(meta.get("car_type") or "sedan"),
        aspects={
            key: float(value)
            for key in ("tire_width_mm", "tire_aspect_pct", "rim_in")
            if (value := meta.get(key)) is not None
        },
    )
    symptom_text = str(meta.get("symptom") or meta.get("complaint") or "").strip()
    symptom = Symptom(description=symptom_text) if symptom_text else Symptom.unspecified()
    test_run = test_run_from_summary(summary)
    case = DiagnosticCase(
        case_id=_require_authoritative_case_id(summary),
        car=car,
        symptoms=(symptom,),
        configuration_snapshots=(test_run.configuration_snapshot,),
        test_plan=test_run.test_plan,
    )
    return case.add_run(test_run)


def project_summary_through_domain(summary: Mapping[str, object]) -> dict[str, object]:
    """Return *summary* with domain-owned fields rebuilt from aggregates."""
    projected = dict(summary)
    raw_findings = summary.get("findings")
    raw_top_causes = summary.get("top_causes")
    if not isinstance(raw_findings, list) and not isinstance(raw_top_causes, list):
        return projected

    test_run = test_run_from_summary(summary)

    findings_by_id = _payloads_by_id(summary.get("findings"))
    top_causes_by_id = _payloads_by_id(summary.get("top_causes"))

    projected["findings"] = [
        finding_payload_from_domain(
            finding,
            primary=findings_by_id,
            secondary=top_causes_by_id,
        )
        for finding in test_run.findings
    ]
    projected["top_causes"] = [
        finding_payload_from_domain(
            finding,
            primary=top_causes_by_id,
            secondary=findings_by_id,
        )
        for finding in test_run.effective_top_causes()
    ]
    _origin_fallback = summary.get("most_likely_origin")
    if not isinstance(_origin_fallback, Mapping):
        _origin_fallback_payload: dict[str, object] = {}
    else:
        _origin_fallback_payload = dict(_origin_fallback)
    _primary = test_run.primary_finding
    projected["most_likely_origin"] = (
        origin_payload_from_finding(_primary, _origin_fallback_payload)
        if _primary is not None
        else _origin_fallback_payload
    )
    if not _has_structured_step_content(summary.get("test_plan")):
        projected["test_plan"] = step_payloads_from_plan(test_run.test_plan)
    projected["run_suitability"] = _checks_from_suitability(test_run.suitability)

    return projected
