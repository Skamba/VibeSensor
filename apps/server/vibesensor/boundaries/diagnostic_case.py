"""Domain <-> summary boundary conversions for diagnostic cases and runs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from ..domain.car import Car
from ..domain.confidence_assessment import ConfidenceAssessment
from ..domain.configuration_snapshot import ConfigurationSnapshot
from ..domain.diagnostic_case import DiagnosticCase
from ..domain.diagnostic_reasoning import DiagnosticReasoning
from ..domain.driving_phase import DrivingPhase
from ..domain.driving_segment import DrivingSegment
from ..domain.finding import Finding
from ..domain.hypothesis import Hypothesis
from ..domain.recommended_action import RecommendedAction
from ..domain.run_capture import RunCapture
from ..domain.run_setup import RunSetup
from ..domain.sensor import Sensor
from ..domain.signature import Signature
from ..domain.speed_source import SpeedSource
from ..domain.symptom import Symptom
from ..domain.test_plan import TestPlan
from ..domain.test_run import TestRun
from ._helpers import _as_float, _has_structured_step_content, _payloads_by_id
from .finding import finding_from_payload, finding_payload_from_domain
from .run_suitability import run_suitability_from_payload, run_suitability_payload
from .speed_profile import speed_profile_from_stats
from .test_steps import step_payloads_from_plan
from .vibration_origin import origin_payload_from_finding


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
                start_idx=(
                    int(_si) if (_si := _as_float(segment.get("start_idx"))) is not None else None
                ),
                end_idx=(
                    int(_ei) if (_ei := _as_float(segment.get("end_idx"))) is not None else None
                ),
                start_t_s=_as_float(segment.get("start_t_s")),
                end_t_s=_as_float(segment.get("end_t_s")),
                speed_min_kmh=_as_float(segment.get("speed_min_kmh")),
                speed_max_kmh=_as_float(segment.get("speed_max_kmh")),
                sample_count=int(_as_float(segment.get("sample_count")) or 0),
            )
        )
    return tuple(segments)


def _enrich_findings(raw_findings: object) -> tuple[Finding, ...]:
    if not isinstance(raw_findings, list):
        return ()
    enriched: list[Finding] = []
    for payload in raw_findings:
        if not isinstance(payload, Mapping):
            continue
        enriched.append(finding_from_payload(payload))
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


def test_run_from_summary(summary: Mapping[str, object]) -> TestRun:
    metadata = summary.get("metadata")
    meta = metadata if isinstance(metadata, Mapping) else {}
    findings = _enrich_findings(summary.get("findings"))
    top_causes = _enrich_findings(summary.get("top_causes"))
    # Historical payload data may have top_causes not present in findings.
    # Merge any unmatched into findings so the domain invariant holds.
    if top_causes:
        merged = list(findings)
        for tc in top_causes:
            if not any(tc == f or (tc.finding_id and tc.finding_id == f.finding_id) for f in merged):
                merged.append(tc)
        findings = tuple(merged)
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

    # Synthesize ConfidenceAssessment for historical findings that lack it
    _steady = speed_profile.steady_speed if speed_profile is not None else True
    _raw_locs = summary.get("sensor_locations")
    _sensor_count = len(_raw_locs) if isinstance(_raw_locs, Mapping) else 0
    _amp_summary = summary.get("amplitude_summary")
    _band_key = (
        _amp_summary.get("overall_band", "moderate")
        if isinstance(_amp_summary, Mapping)
        else "moderate"
    )
    _has_ref_gaps = False
    if isinstance(run_suitability, list):
        for _chk in run_suitability:
            if (
                isinstance(_chk, Mapping)
                and _chk.get("check_key") == "reference_complete"
                and _chk.get("state") == "fail"
            ):
                _has_ref_gaps = True
                break

    def _ensure_ca(f: Finding) -> Finding:
        if f.confidence_assessment is not None:
            return f
        ca = ConfidenceAssessment.assess(
            f.effective_confidence,
            strength_band_key=_band_key,
            steady_speed=_steady,
            has_reference_gaps=_has_ref_gaps,
            weak_spatial=f.weak_spatial_separation,
            sensor_count=max(_sensor_count, 1),
        )
        return replace(f, confidence_assessment=ca)

    findings = tuple(_ensure_ca(f) for f in findings)
    top_causes = tuple(_ensure_ca(f) for f in top_causes)

    signatures: list[Signature] = []
    hypotheses: list[Hypothesis] = []
    for finding in findings:
        if finding.is_reference:
            continue  # reference findings don't produce hypotheses
        signatures.extend(finding.signatures)
        hypotheses.append(Hypothesis.from_finding(finding, finding.signatures))

    sensor_locs = summary.get("sensor_locations")
    sensor_loc_list = list(sensor_locs) if isinstance(sensor_locs, Mapping) else []
    setup = RunSetup(
        sensors=Sensor.from_location_codes(sensor_loc_list) if sensor_loc_list else (),
        speed_source=SpeedSource(),
        configuration_snapshot=ConfigurationSnapshot.from_metadata(meta),
    )
    capture = RunCapture(
        run_id=str(summary.get("run_id") or "unknown"),
        setup=setup,
    )
    reasoning_obj = DiagnosticReasoning(
        signatures=tuple(dict.fromkeys(signatures)),
        hypotheses=tuple(hypotheses),
    )

    return TestRun(
        capture=capture,
        reasoning=reasoning_obj,
        driving_segments=_segments_from_summary(summary),
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
    projected["run_suitability"] = run_suitability_payload(test_run.suitability)

    return projected
