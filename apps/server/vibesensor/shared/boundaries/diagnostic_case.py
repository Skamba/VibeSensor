"""Domain <-> summary boundary conversions for diagnostic cases and runs.

Also includes boundary functions for run suitability and speed profile
(formerly in separate modules).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from vibesensor.domain.car import Car
from vibesensor.domain.diagnostic_case import DiagnosticCase, Symptom
from vibesensor.domain.driving_segment import DrivingPhase, DrivingSegment
from vibesensor.domain.finding import Finding
from vibesensor.domain.run_capture import ConfigurationSnapshot, RunCapture, RunSetup
from vibesensor.domain.run_suitability import RunSuitability, SuitabilityCheck
from vibesensor.domain.sensor import Sensor
from vibesensor.domain.snapshots import PhaseSummarySnapshot, SpeedStatsSnapshot
from vibesensor.domain.speed_profile import SpeedProfile
from vibesensor.domain.speed_source import SpeedSource
from vibesensor.domain.test_plan import RecommendedAction, TestPlan
from vibesensor.domain.test_run import TestRun
from vibesensor.shared.boundaries.finding import (
    _has_structured_step_content,
    finding_from_payload,
    finding_payload_from_domain,
    step_payloads_from_plan,
)
from vibesensor.shared.boundaries.vibration_origin import origin_payload_from_finding
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.types.json_types import JsonObject

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


def _payload_for_check(check: SuitabilityCheck) -> dict[str, object]:
    return {
        "check": check.check_key,
        "check_key": check.check_key,
        "state": check.state,
        "explanation": check.explanation_i18n_ref(),
    }


def run_suitability_payload(
    suitability: RunSuitability | None,
) -> list[dict[str, object]]:
    """Project a domain RunSuitability into the persisted checklist payload shape."""
    if suitability is None:
        return []
    return [_payload_for_check(check) for check in suitability.checks]


# ---------------------------------------------------------------------------
# Analysis summary projection (shared by history services)
# ---------------------------------------------------------------------------


def project_analysis_summary(analysis: JsonObject) -> tuple[JsonObject, TestRun | None]:
    """Round-trip an analysis dict through the domain model.

    Returns ``(projected, test_run)`` where *projected* is a shallow copy of
    *analysis* with findings, top causes, origin, test plan, and suitability
    re-serialised from the domain ``TestRun``.

    Summaries written by the current pipeline carry ``_summary_version == 2``
    and are already fully projected, so the expensive round-trip is skipped.
    The ``TestRun`` is returned as *None* in that case — callers that need
    a domain aggregate (e.g. report rendering) reconstruct it themselves.
    """
    if analysis.get("_summary_version") == 2:
        return analysis, None

    test_run = test_run_from_summary(analysis)
    projected: JsonObject = dict(analysis)
    projected["findings"] = [finding_payload_from_domain(f) for f in test_run.findings]
    projected["top_causes"] = [
        finding_payload_from_domain(f) for f in test_run.effective_top_causes()
    ]
    primary = test_run.primary_finding
    origin_fb = analysis.get("most_likely_origin")
    fb_payload = dict(origin_fb) if isinstance(origin_fb, Mapping) else {}
    projected["most_likely_origin"] = (
        origin_payload_from_finding(primary, fb_payload) if primary is not None else fb_payload
    )
    if not _has_structured_step_content(analysis.get("test_plan")):
        projected["test_plan"] = step_payloads_from_plan(test_run.test_plan)
    projected["run_suitability"] = run_suitability_payload(test_run.suitability)
    return projected, test_run


# ---------------------------------------------------------------------------
# Speed profile (formerly speed_profile.py)
# ---------------------------------------------------------------------------


def speed_profile_from_stats(
    speed_stats: SpeedStatsSnapshot,
    phase_summary: PhaseSummarySnapshot | None = None,
) -> SpeedProfile:
    """Construct a ``SpeedProfile`` from typed speed-stats and phase-summary snapshots."""
    ps = phase_summary or PhaseSummarySnapshot()

    def _or_zero(v: float | None) -> float:
        return v if v is not None else 0.0

    return SpeedProfile(
        min_kmh=_or_zero(speed_stats.min_kmh),
        max_kmh=_or_zero(speed_stats.max_kmh),
        mean_kmh=_or_zero(speed_stats.mean_kmh),
        stddev_kmh=_or_zero(speed_stats.stddev_kmh),
        steady_speed=speed_stats.steady_speed,
        has_cruise=ps.has_cruise,
        has_acceleration=ps.has_acceleration,
        cruise_fraction=min(1.0, max(0.0, ps.cruise_pct / 100.0)) if ps.cruise_pct else 0.0,
        idle_fraction=min(1.0, max(0.0, ps.idle_pct / 100.0)) if ps.idle_pct else 0.0,
        speed_unknown_fraction=(
            min(1.0, max(0.0, ps.speed_unknown_pct / 100.0)) if ps.speed_unknown_pct else 0.0
        ),
        sample_count=speed_stats.sample_count,
    )


# ---------------------------------------------------------------------------
# Diagnostic case / test run reconstruction
# ---------------------------------------------------------------------------


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
            if not any(
                tc == f or (tc.finding_id and tc.finding_id == f.finding_id) for f in merged
            ):
                merged.append(tc)
        findings = tuple(merged)
    actions = _actions_from_steps(summary.get("test_plan"))
    raw_speed_stats = summary.get("speed_stats")
    phase_info = summary.get("phase_info")
    if not isinstance(phase_info, Mapping):
        phase_info = summary.get("phase_summary")
    speed_profile = (
        speed_profile_from_stats(
            SpeedStatsSnapshot.from_dict(raw_speed_stats),
            PhaseSummarySnapshot.from_dict(phase_info) if isinstance(phase_info, Mapping) else None,
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
