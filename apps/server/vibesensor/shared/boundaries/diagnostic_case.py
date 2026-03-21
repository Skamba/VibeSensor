"""Decode persisted diagnostic summaries and project canonical summary payloads.

This module is the boundary decoder/projection layer for persisted analysis
summaries. Construction from already-typed internal metadata or speed snapshots
belongs on the domain objects themselves.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import cast

from vibesensor.domain import Car, Finding, LocationHotspot, VibrationOrigin
from vibesensor.domain.diagnostic_case import DiagnosticCase, Symptom
from vibesensor.domain.driving_phase_summary import DrivingPhaseSummary
from vibesensor.domain.driving_segment import DrivingPhase, DrivingSegment
from vibesensor.domain.run_capture import ConfigurationSnapshot, RunCapture, RunSetup
from vibesensor.domain.run_suitability import RunSuitability, SuitabilityCheck
from vibesensor.domain.sensor import Sensor
from vibesensor.domain.speed_profile import SpeedProfile
from vibesensor.domain.speed_profile_summary import SpeedProfileSummary
from vibesensor.domain.speed_source import SpeedSource
from vibesensor.domain.test_plan import RecommendedAction, TestPlan
from vibesensor.domain.test_run import TestRun
from vibesensor.shared.boundaries.analysis_payload import RunSuitabilityCheck
from vibesensor.shared.boundaries.finding import (
    _has_structured_step_content,
    finding_from_payload,
    finding_payload_from_domain,
    step_payloads_from_plan,
)
from vibesensor.shared.boundaries.vibration_origin import origin_payload_from_finding
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.types.json_types import JsonObject, JsonValue

# ---------------------------------------------------------------------------
# Run suitability (formerly run_suitability.py)
# ---------------------------------------------------------------------------


def run_suitability_from_payload(checks: Sequence[Mapping[str, object]]) -> RunSuitability:
    """Decode persisted checklist payloads into the domain RunSuitability shape."""
    domain_checks = tuple(
        SuitabilityCheck(
            check_key=str(c.get("check_key", c.get("check", ""))),
            state=str(c.get("state", "pass")),
        )
        for c in checks
        if isinstance(c, Mapping)
    )
    return RunSuitability(checks=domain_checks)


def _payload_for_check(check: SuitabilityCheck) -> RunSuitabilityCheck:
    return {
        "check": check.check_key,
        "check_key": check.check_key,
        "state": check.state,
        "explanation": cast(JsonValue, check.explanation_i18n_ref()),
    }


def run_suitability_payload(
    suitability: RunSuitability | None,
) -> list[RunSuitabilityCheck]:
    """Project a domain RunSuitability into the persisted checklist payload shape."""
    if suitability is None:
        return []
    return [_payload_for_check(check) for check in suitability.checks]


# ---------------------------------------------------------------------------
# Analysis summary projection (shared by history services)
# ---------------------------------------------------------------------------


def project_analysis_summary(analysis: JsonObject) -> tuple[JsonObject, TestRun]:
    """Reconstruct and re-serialize analysis through the canonical domain boundary.

    Returns ``(projected, test_run)`` where *projected* is a shallow copy of
    *analysis* with findings, top causes, origin, test plan, and suitability
    serialized from the domain ``TestRun``.
    """
    test_run = test_run_from_summary(analysis)
    # Work with dict[str, object] to match boundary function return types;
    # cast to JsonObject at the return boundary.
    projected: dict[str, object] = dict(analysis)
    projected["findings"] = [finding_payload_from_domain(f) for f in test_run.findings]
    projected["top_causes"] = [
        finding_payload_from_domain(f) for f in test_run.effective_top_causes()
    ]
    primary = test_run.primary_finding
    origin_fb = analysis.get("most_likely_origin")
    fb_payload = dict(origin_fb) if isinstance(origin_fb, Mapping) else {}
    if primary is None:
        projected["most_likely_origin"] = fb_payload
    else:
        projected["most_likely_origin"] = origin_payload_from_finding(primary)
    if not _has_structured_step_content(analysis.get("test_plan")):
        projected["test_plan"] = step_payloads_from_plan(test_run.test_plan)
    projected["run_suitability"] = run_suitability_payload(test_run.suitability)
    return cast(JsonObject, projected), test_run


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


def _matches_finding(candidate: Finding, target: Finding) -> bool:
    if candidate == target:
        return True
    if not (candidate.finding_id and candidate.finding_id == target.finding_id):
        return False
    return (
        candidate.finding_key == target.finding_key
        and candidate.strongest_location == target.strongest_location
        and candidate.strongest_speed_band == target.strongest_speed_band
        and candidate.frequency_hz == target.frequency_hz
        and candidate.order == target.order
        and candidate.suspected_source == target.suspected_source
    )


def _domain_origin_from_summary_payload(
    payload: Mapping[str, object],
    *,
    primary: Finding,
    domain_origin: VibrationOrigin | None,
) -> VibrationOrigin | None:
    raw_location = str(payload.get("location") or "").strip()
    if not raw_location or raw_location.lower() == "unknown":
        return None
    strongest_location = raw_location.split(" / ", maxsplit=1)[0].strip()
    if not strongest_location or strongest_location.lower() == "unknown":
        return None
    alternatives_raw = payload.get("alternative_locations")
    alternatives = (
        tuple(str(location).strip() for location in alternatives_raw if str(location).strip())
        if isinstance(alternatives_raw, list)
        else ()
    )
    dominance_ratio = (
        domain_origin.dominance_ratio
        if domain_origin is not None and domain_origin.dominance_ratio is not None
        else primary.dominance_ratio
    )
    if dominance_ratio is None:
        dominance_ratio = _as_float(payload.get("dominance_ratio"))
    hotspot = LocationHotspot.from_analysis_inputs(
        strongest_location=strongest_location,
        dominance_ratio=dominance_ratio,
        weak_spatial_separation=(
            (domain_origin.weak_spatial_separation if domain_origin is not None else False)
            or primary.weak_spatial_separation
            or bool(payload.get("weak_spatial_separation", False))
            or bool(alternatives)
        ),
        ambiguous=bool(alternatives),
        alternative_locations=alternatives,
    )
    return VibrationOrigin.from_analysis_inputs(
        suspected_source=(
            domain_origin.suspected_source
            if domain_origin is not None
            else primary.suspected_source
        ),
        hotspot=hotspot,
        dominance_ratio=dominance_ratio,
        speed_band=(
            domain_origin.speed_band
            if domain_origin is not None and domain_origin.speed_band is not None
            else primary.strongest_speed_band
            or (str(payload.get("speed_band") or "").strip() or None)
        ),
        dominant_phase=(
            domain_origin.dominant_phase
            if domain_origin is not None and domain_origin.dominant_phase is not None
            else primary.dominant_phase
            or (str(payload.get("dominant_phase") or "").strip() or None)
        ),
        reason=domain_origin.reason if domain_origin is not None else "",
    )


def _enrich_primary_origin_from_summary(
    summary: Mapping[str, object],
    *,
    findings: tuple[Finding, ...],
    top_causes: tuple[Finding, ...],
) -> tuple[tuple[Finding, ...], tuple[Finding, ...]]:
    summary_origin = summary.get("most_likely_origin")
    if not isinstance(summary_origin, Mapping):
        return findings, top_causes
    primary = top_causes[0] if top_causes else next((f for f in findings if f.is_diagnostic), None)
    if primary is None:
        return findings, top_causes
    domain_origin = VibrationOrigin.from_finding(primary)
    if domain_origin is not None and domain_origin.has_sufficient_location:
        return findings, top_causes
    enriched_origin = _domain_origin_from_summary_payload(
        summary_origin,
        primary=primary,
        domain_origin=domain_origin,
    )
    if enriched_origin is None or enriched_origin.hotspot is None:
        return findings, top_causes
    enriched_primary = replace(
        primary,
        strongest_location=primary.strongest_location or enriched_origin.hotspot.strongest_location,
        dominant_phase=primary.dominant_phase or enriched_origin.dominant_phase,
        dominance_ratio=(
            primary.dominance_ratio
            if primary.dominance_ratio is not None
            else enriched_origin.dominance_ratio
        ),
        weak_spatial_separation=(
            primary.weak_spatial_separation or enriched_origin.weak_spatial_separation
        ),
        location=primary.location or enriched_origin.hotspot,
        origin=enriched_origin,
    )

    def _replace_matches(items: tuple[Finding, ...]) -> tuple[Finding, ...]:
        return tuple(
            enriched_primary if _matches_finding(item, primary) else item for item in items
        )

    return _replace_matches(findings), _replace_matches(top_causes)


def _require_authoritative_case_id(summary: Mapping[str, object]) -> str:
    case_id = summary.get("case_id")
    if isinstance(case_id, str):
        normalized_case_id = case_id.strip()
        if normalized_case_id:
            return normalized_case_id
    raise ValueError("Cannot decode DiagnosticCase from summary without authoritative case_id")


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
            if not any(
                tc == f or (tc.finding_id and tc.finding_id == f.finding_id) for f in merged
            ):
                merged.append(tc)
        findings = tuple(merged)
    findings, top_causes = _enrich_primary_origin_from_summary(
        summary,
        findings=findings,
        top_causes=top_causes,
    )
    actions = _actions_from_steps(summary.get("test_plan"))
    raw_speed_stats = summary.get("speed_stats")
    phase_info = summary.get("phase_info")
    if not isinstance(phase_info, Mapping):
        phase_info = summary.get("phase_summary")
    speed_profile = (
        SpeedProfile.from_stats(
            SpeedProfileSummary.from_dict(raw_speed_stats),
            DrivingPhaseSummary.from_dict(phase_info) if isinstance(phase_info, Mapping) else None,
        )
        if isinstance(raw_speed_stats, Mapping)
        else None
    )
    raw_suitability_payload = summary.get("run_suitability")
    suitability = (
        run_suitability_from_payload(raw_suitability_payload)
        if isinstance(raw_suitability_payload, list)
        else None
    )

    # Synthesize ConfidenceAssessment for historical findings that lack it
    _steady = speed_profile.steady_speed if speed_profile is not None else True
    _raw_locs = summary.get("sensor_locations")
    _sensor_count = max(len(_raw_locs) if isinstance(_raw_locs, Mapping) else 0, 1)
    _amp_summary = summary.get("amplitude_summary")
    _band_key = (
        _amp_summary.get("overall_band", "moderate")
        if isinstance(_amp_summary, Mapping)
        else "moderate"
    )
    _has_ref_gaps = suitability.has_reference_gaps if suitability else False

    # Backfill ConfidenceAssessment for historical findings that lack it.
    findings = tuple(
        f
        if f.confidence_assessment is not None
        else f.with_confidence_assessment(
            strength_band_key=_band_key,
            steady_speed=_steady,
            has_reference_gaps=_has_ref_gaps,
            sensor_count=_sensor_count,
        )
        for f in findings
    )
    top_causes = tuple(
        f
        if f.confidence_assessment is not None
        else f.with_confidence_assessment(
            strength_band_key=_band_key,
            steady_speed=_steady,
            has_reference_gaps=_has_ref_gaps,
            sensor_count=_sensor_count,
        )
        for f in top_causes
    )

    sensor_locs = summary.get("sensor_locations")
    sensor_loc_list = list(sensor_locs) if isinstance(sensor_locs, Mapping) else []
    setup = RunSetup(
        sensors=Sensor.from_location_codes(sensor_loc_list) if sensor_loc_list else (),
        speed_source=SpeedSource(),
        configuration_snapshot=ConfigurationSnapshot.from_metadata(meta),
    )
    rows_raw = summary.get("rows")
    row_count = int(rows_raw) if isinstance(rows_raw, (int, float, str)) else 0
    capture = RunCapture(
        run_id=str(summary.get("run_id") or "unknown"),
        setup=setup,
        sample_count=row_count,
    )
    return TestRun(
        capture=capture,
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
    car = Car.from_metadata(meta)
    symptoms = (Symptom.from_metadata(meta),)
    test_run = test_run_from_summary(summary)
    case = DiagnosticCase(
        case_id=_require_authoritative_case_id(summary),
        car=car,
        symptoms=symptoms,
        test_plan=test_run.test_plan,
    )
    return case.add_run(test_run)
