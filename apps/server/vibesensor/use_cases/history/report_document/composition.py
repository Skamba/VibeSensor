"""Report-document composition from semantic report facts."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from vibesensor.domain import Finding, LocationIntensitySummary, SuitabilityCheck, TestRun
from vibesensor.report_i18n import human_source
from vibesensor.report_i18n import tr as _tr
from vibesensor.shared.boundaries.reporting import PreparedReportFacts
from vibesensor.shared.boundaries.reporting.document import (
    AppendixAData,
    AppendixBData,
    RankedCandidateRow,
    TopologyIntensityRow,
    VerdictPageData,
)
from vibesensor.shared.boundaries.reporting.projection import PrimaryReportFacts
from vibesensor.shared.report_diagnostics import (
    check_state,
    first_nonpass_detail,
    has_warning_code,
    nonpass_detail_lines,
)
from vibesensor.shared.report_presentation import (
    action_status_text,
    append_unique_line,
    candidate_signal_text,
    confidence_pct_text,
    coverage_label,
    coverage_notes,
    display_location,
    first_confidence_reason_clause,
    has_source_overlap,
    is_transient_primary,
    location_confidence_text,
    presented_location_confidence_key,
    proof_caveat_text,
    runner_up_corner,
    source_with_confidence,
    uses_shared_overlap_wording,
)
from vibesensor.shared.run_context_warning import RunContextWarning
from vibesensor.shared.types.json_types import JsonValue
from vibesensor.use_cases.history.report_observation_matrix import (
    build_sensor_observation_matrix_rows,
)

__all__ = ["ReportDocumentComposition", "compose_report_document"]


@dataclass(frozen=True, slots=True)
class ReportDocumentComposition:
    """Document-facing verdict and appendix content composed from report facts."""

    verdict_page: VerdictPageData
    appendix_a: AppendixAData
    appendix_b: AppendixBData


def compose_report_document(
    *,
    aggregate: TestRun,
    report_facts: PreparedReportFacts,
    lang: str,
) -> ReportDocumentComposition:
    """Build presentation-specific report sections from prepared semantic facts."""

    def tr(key: str, **kw: JsonValue) -> str:
        return str(_tr(lang, key, **kw))

    coverage = report_facts.coverage_summary
    resolved_coverage_label = coverage_label(
        expected_locations=coverage.expected_locations,
        active_locations=coverage.active_locations,
        missing_locations=coverage.missing_locations,
        partial_locations=coverage.partial_locations,
        tr=tr,
    )
    resolved_coverage_notes = coverage_notes(
        missing_locations=coverage.missing_locations,
        partial_locations=coverage.partial_locations,
        tr=tr,
    )
    resolved_runner_up_corner = runner_up_corner(
        report_facts.active_sensor_intensity,
        tr=tr,
    )
    proof_caveat = proof_caveat_text(
        primary_candidate_facts=report_facts.primary_candidate_facts,
        action_status_key=report_facts.action_status_key,
        location_confidence_key=report_facts.location_confidence_key,
        tr=tr,
    )
    ranked_candidates = _build_ranked_candidates(aggregate, tr=tr)
    recapture_issues = _recapture_issue_lines(
        aggregate=aggregate,
        primary_candidate_facts=report_facts.primary_candidate_facts,
        location_confidence_key=report_facts.location_confidence_key,
        suitability_checks=report_facts.suitability_checks,
        warnings=report_facts.warnings,
        lang=lang,
        tr=tr,
    )
    recapture_actions = _recapture_actions(
        aggregate=aggregate,
        primary_candidate_facts=report_facts.primary_candidate_facts,
        location_confidence_key=report_facts.location_confidence_key,
        expected_locations=coverage.expected_locations,
        active_locations=coverage.active_locations,
        suitability_checks=report_facts.suitability_checks,
        warnings=report_facts.warnings,
        tr=tr,
    )
    recapture_conditions = _recapture_condition_lines(
        aggregate=aggregate,
        primary_candidate_facts=report_facts.primary_candidate_facts,
        location_confidence_key=report_facts.location_confidence_key,
        expected_locations=coverage.expected_locations,
        active_locations=coverage.active_locations,
        suitability_checks=report_facts.suitability_checks,
        warnings=report_facts.warnings,
        tr=tr,
    )
    return ReportDocumentComposition(
        verdict_page=_build_verdict_page_data(
            aggregate=aggregate,
            primary_candidate_facts=report_facts.primary_candidate_facts,
            duration_text=report_facts.duration_text,
            action_status_key=report_facts.action_status_key,
            location_confidence_key=report_facts.location_confidence_key,
            alternative_source_visible=report_facts.alternative_source_visible,
            active_locations=coverage.active_locations,
            coverage_label=resolved_coverage_label,
            runner_up_corner=resolved_runner_up_corner,
            proof_caveat=proof_caveat,
            recapture_issues=recapture_issues,
            suitability_checks=report_facts.suitability_checks,
            warnings=report_facts.warnings,
            lang=lang,
            tr=tr,
        ),
        appendix_a=_build_appendix_a_data(
            aggregate=aggregate,
            action_status_key=report_facts.action_status_key,
            alternative_source_visible=report_facts.alternative_source_visible,
            ranked_candidates=ranked_candidates,
            recapture_issues=recapture_issues,
            recapture_actions=recapture_actions,
            recapture_conditions=recapture_conditions,
            tr=tr,
        ),
        appendix_b=_build_appendix_b_data(
            aggregate=aggregate,
            primary_candidate_facts=report_facts.primary_candidate_facts,
            active_sensor_intensity=report_facts.active_sensor_intensity,
            action_status_key=report_facts.action_status_key,
            location_confidence_key=report_facts.location_confidence_key,
            active_locations=coverage.active_locations,
            runner_up_corner=resolved_runner_up_corner,
            coverage_label=resolved_coverage_label,
            coverage_notes=resolved_coverage_notes,
            tr=tr,
        ),
    )


def _build_verdict_page_data(
    *,
    aggregate: TestRun,
    primary_candidate_facts: PrimaryReportFacts,
    duration_text: str | None,
    action_status_key: str,
    location_confidence_key: str,
    alternative_source_visible: bool,
    active_locations: Sequence[str],
    coverage_label: str,
    runner_up_corner: str | None,
    proof_caveat: str | None,
    recapture_issues: Sequence[str],
    suitability_checks: Sequence[SuitabilityCheck],
    warnings: Sequence[RunContextWarning],
    lang: str,
    tr: Callable[..., str],
) -> VerdictPageData:
    recapture_before_acting = action_status_key == "recapture_before_acting"
    return VerdictPageData(
        speed_window_label=str(primary_candidate_facts.primary_speed or "").strip() or None,
        suspected_source=(
            tr("REPORT_INCONCLUSIVE_SOURCE")
            if recapture_before_acting
            else _primary_source_text(primary_candidate_facts, tr=tr)
        ),
        inspect_first=(
            None
            if recapture_before_acting
            else display_location(primary_candidate_facts.primary_location, tr=tr)
        ),
        action_status=action_status_text(action_status_key, tr=tr),
        action_status_note=_action_status_note_text(
            aggregate=aggregate,
            primary_candidate_facts=primary_candidate_facts,
            action_status_key=action_status_key,
            location_confidence_key=location_confidence_key,
            alternative_source_visible=alternative_source_visible,
            suitability_checks=suitability_checks,
            warnings=warnings,
            lang=lang,
            tr=tr,
        ),
        reason_sentence=(
            recapture_issues[0]
            if recapture_before_acting and recapture_issues
            else _build_primary_reason_sentence(
                primary_candidate_facts=primary_candidate_facts,
                active_locations=active_locations,
                duration_text=duration_text,
                tr=tr,
            )
        ),
        dominant_corner=display_location(primary_candidate_facts.primary_location, tr=tr),
        runner_up_corner=runner_up_corner,
        location_confidence=_location_confidence_display_text(
            primary_candidate_facts=primary_candidate_facts,
            action_status_key=action_status_key,
            location_confidence_key=location_confidence_key,
            alternative_source_visible=alternative_source_visible,
            dominance_ratio=primary_candidate_facts.dominance_ratio,
            suitability_checks=suitability_checks,
            warnings=warnings,
            lang=lang,
            tr=tr,
        ),
        coverage_label=coverage_label,
        also_consider=(
            source_with_confidence(aggregate.effective_top_causes()[1], tr=tr)
            if not recapture_before_acting
            and alternative_source_visible
            and len(aggregate.effective_top_causes()) > 1
            else None
        ),
        proof_caveat=proof_caveat,
        proof_panel_title=(
            tr("REPORT_PROOF_PANEL_TITLE_INCONCLUSIVE")
            if recapture_before_acting
            else tr("REPORT_PROOF_PANEL_TITLE")
        ),
        footer_routes=(
            (tr("REPORT_ROUTE_APPENDIX_A"),)
            if recapture_before_acting
            else (
                tr("REPORT_ROUTE_APPENDIX_A"),
                tr("REPORT_ROUTE_APPENDIX_B"),
                tr("REPORT_ROUTE_APPENDIX_C"),
                tr("REPORT_ROUTE_APPENDIX_D"),
            )
        ),
    )


def _build_primary_reason_sentence(
    *,
    primary_candidate_facts: PrimaryReportFacts,
    active_locations: Sequence[str],
    duration_text: str | None,
    tr: Callable[..., str],
) -> str:
    location = display_location(primary_candidate_facts.primary_location, tr=tr)
    duration = str(duration_text or "").strip() or tr("UNKNOWN")
    sensor_count = len(active_locations) or primary_candidate_facts.sensor_count
    speed_window = str(primary_candidate_facts.primary_speed or "").strip()
    if speed_window and speed_window != tr("UNKNOWN"):
        return tr(
            "REPORT_REASON_RUN_SUMMARY",
            duration=duration,
            location=location,
            speed=speed_window,
            sensors=sensor_count,
        )
    return tr(
        "REPORT_REASON_RUN_SUMMARY_NO_SPEED",
        duration=duration,
        location=location,
        sensors=sensor_count,
    )


def _location_confidence_display_text(
    *,
    primary_candidate_facts: PrimaryReportFacts,
    action_status_key: str,
    location_confidence_key: str,
    alternative_source_visible: bool,
    dominance_ratio: float | None,
    suitability_checks: Sequence[SuitabilityCheck],
    warnings: Sequence[RunContextWarning],
    lang: str,
    tr: Callable[..., str],
) -> str:
    presented_key = presented_location_confidence_key(
        action_status_key=action_status_key,
        location_confidence_key=location_confidence_key,
    )
    if action_status_key != "action_ready_caution":
        return location_confidence_text(presented_key, tr=tr)

    reason = first_confidence_reason_clause(primary_candidate_facts)
    if reason:
        return reason
    if alternative_source_visible:
        return tr("REPORT_LOCATION_CONFIDENCE_CLOSE_SCORES")
    issue = first_nonpass_detail(
        suitability_checks=suitability_checks,
        warnings=warnings,
        lang=lang,
        tr=tr,
    )
    if issue:
        return issue.rstrip(".")
    if dominance_ratio is not None:
        return tr("REPORT_LOCATION_CONFIDENCE_RATIO_REASON", ratio=f"{dominance_ratio:.1f}")
    return tr("REPORT_LOCATION_CONFIDENCE_MODERATE_DETAIL")


def _action_status_note_text(
    *,
    aggregate: TestRun,
    primary_candidate_facts: PrimaryReportFacts,
    action_status_key: str,
    location_confidence_key: str,
    alternative_source_visible: bool,
    suitability_checks: Sequence[SuitabilityCheck],
    warnings: Sequence[RunContextWarning],
    lang: str,
    tr: Callable[..., str],
) -> str | None:
    if action_status_key not in {"action_ready_caution", "recapture_before_acting"}:
        return None
    issue = first_nonpass_detail(
        suitability_checks=suitability_checks,
        warnings=warnings,
        lang=lang,
        tr=tr,
    )
    score_note: str | None = None
    if action_status_key == "action_ready_caution" and alternative_source_visible:
        ranked_candidates = list(aggregate.effective_top_causes()[:2])
        if len(ranked_candidates) > 1:
            score_note = tr(
                "REPORT_ACTION_STATUS_NOTE_GATE_CAUTION_WITH_SCORES",
                primary=human_source(ranked_candidates[0].suspected_source, tr=tr),
                primary_confidence=confidence_pct_text(ranked_candidates[0]),
                alternative=human_source(ranked_candidates[1].suspected_source, tr=tr),
                alternative_confidence=confidence_pct_text(ranked_candidates[1]),
            )
        else:
            score_note = tr("REPORT_ACTION_STATUS_NOTE_GATE_CAUTION")
    reason = score_note or proof_caveat_text(
        primary_candidate_facts=primary_candidate_facts,
        action_status_key=action_status_key,
        location_confidence_key=location_confidence_key,
        tr=tr,
    )
    if issue and reason:
        issue_norm = issue.rstrip(".")
        reason_norm = reason.rstrip(".")
        if reason_norm.casefold() not in issue_norm.casefold():
            return tr(
                "REPORT_ACTION_STATUS_NOTE_COMBINED",
                issue=issue_norm,
                reason=reason_norm,
            )
        return issue
    return issue or reason


def _primary_source_text(
    primary_candidate_facts: PrimaryReportFacts,
    *,
    tr: Callable[..., str],
) -> str:
    if primary_candidate_facts.primary_source is None:
        return tr("UNKNOWN")
    return human_source(primary_candidate_facts.primary_source, tr=tr)


def _build_appendix_a_data(
    *,
    aggregate: TestRun,
    action_status_key: str,
    alternative_source_visible: bool,
    ranked_candidates: Sequence[RankedCandidateRow],
    recapture_issues: Sequence[str],
    recapture_actions: Sequence[str],
    recapture_conditions: Sequence[str],
    tr: Callable[..., str],
) -> AppendixAData:
    recapture_before_acting = action_status_key == "recapture_before_acting"
    if recapture_before_acting:
        return AppendixAData(
            mode="recapture",
            primary_source=None,
            alternative_source=None,
            why_primary_first=None,
            why_alternative_next=None,
            next_if_clean=None,
            ranked_candidates=[],
            capture_issues=list(recapture_issues),
            capture_changes=list(recapture_actions),
            capture_conditions=list(recapture_conditions),
        )

    primary_source = (
        tr(
            "REPORT_SOURCE_WITH_CONFIDENCE",
            source=ranked_candidates[0].source_name,
            confidence=ranked_candidates[0].confidence_pct,
        )
        if ranked_candidates and ranked_candidates[0].confidence_pct
        else ranked_candidates[0].source_name
        if ranked_candidates
        else None
    )
    alternative_source = (
        tr(
            "REPORT_SOURCE_WITH_CONFIDENCE",
            source=ranked_candidates[1].source_name,
            confidence=ranked_candidates[1].confidence_pct,
        )
        if alternative_source_visible
        and len(ranked_candidates) > 1
        and ranked_candidates[1].confidence_pct
        else ranked_candidates[1].source_name
        if alternative_source_visible and len(ranked_candidates) > 1
        else None
    )
    return AppendixAData(
        mode="workflow",
        primary_source=primary_source,
        alternative_source=alternative_source,
        why_primary_first=ranked_candidates[0].reason if ranked_candidates else None,
        why_alternative_next=(
            ranked_candidates[1].reason
            if alternative_source_visible and len(ranked_candidates) > 1
            else None
        ),
        next_if_clean=_next_if_primary_clean(aggregate, tr=tr),
        ranked_candidates=list(ranked_candidates),
        capture_issues=[],
        capture_changes=[],
        capture_conditions=[],
    )


def _build_appendix_b_data(
    *,
    aggregate: TestRun,
    primary_candidate_facts: PrimaryReportFacts,
    active_sensor_intensity: Sequence[LocationIntensitySummary],
    action_status_key: str,
    location_confidence_key: str,
    active_locations: Sequence[str],
    runner_up_corner: str | None,
    coverage_label: str,
    coverage_notes: Sequence[str],
    tr: Callable[..., str],
) -> AppendixBData:
    dominance_ratio_text = (
        tr(
            "REPORT_DOMINANCE_RATIO_TEXT",
            ratio=f"{primary_candidate_facts.dominance_ratio:.2f}",
        )
        if primary_candidate_facts.dominance_ratio is not None
        else tr("REPORT_DOMINANCE_RATIO_UNKNOWN")
    )
    ranked_rows = sorted(
        active_sensor_intensity,
        key=lambda row: (
            row.p95_intensity_db if row.p95_intensity_db is not None else float("-inf"),
        ),
        reverse=True,
    )
    intensity_rows = [
        TopologyIntensityRow(
            location=display_location(row.location, short=False, tr=tr),
            p95_db=row.p95_intensity_db,
            coverage_state=(
                tr("REPORT_COVERAGE_STATE_PARTIAL")
                if row.partial_coverage or row.sample_coverage_warning
                else tr("REPORT_COVERAGE_STATE_COMPLETE")
            ),
        )
        for row in ranked_rows
    ]
    return AppendixBData(
        dominant_corner=display_location(primary_candidate_facts.primary_location, tr=tr),
        runner_up_corner=runner_up_corner,
        dominance_ratio_text=dominance_ratio_text,
        location_confidence=location_confidence_text(
            presented_location_confidence_key(
                action_status_key=action_status_key,
                location_confidence_key=location_confidence_key,
            ),
            tr=tr,
        ),
        coverage_label=coverage_label,
        coverage_notes=list(coverage_notes),
        intensity_rows=intensity_rows,
        sensor_observation_rows=build_sensor_observation_matrix_rows(
            aggregate,
            sensor_locations=list(active_locations),
            tr=tr,
        ),
    )


def _build_ranked_candidates(
    aggregate: TestRun,
    *,
    tr: Callable[..., str],
) -> tuple[RankedCandidateRow, ...]:
    candidates = list(aggregate.effective_top_causes()[:3])
    rows: list[RankedCandidateRow] = []
    primary_finding = candidates[0] if candidates else None
    for index, finding in enumerate(candidates):
        use_shared_overlap_wording = (
            index > 0
            and primary_finding is not None
            and uses_shared_overlap_wording(primary_finding, finding, tr=tr)
        )
        rows.append(
            RankedCandidateRow(
                source_name=human_source(finding.suspected_source, tr=tr),
                confidence_pct=confidence_pct_text(finding),
                inspect_first=display_location(finding.strongest_location, tr=tr),
                path_role=f"{index + 1}. {_path_role_text(index, tr=tr)}",
                reason=_candidate_reason_text(
                    finding,
                    tr=tr,
                    use_shared_overlap_wording=use_shared_overlap_wording,
                ),
            ),
        )
    return tuple(rows)


def _next_if_primary_clean(
    aggregate: TestRun,
    *,
    tr: Callable[..., str],
) -> str | None:
    candidates = list(aggregate.effective_top_causes()[:2])
    if len(candidates) < 2:
        return None
    alternative = candidates[1]
    use_shared_overlap_wording = uses_shared_overlap_wording(candidates[0], alternative, tr=tr)
    return _candidate_reason_text(
        alternative,
        tr=tr,
        use_shared_overlap_wording=use_shared_overlap_wording,
    )


def _candidate_reason_text(
    finding: Finding,
    *,
    tr: Callable[..., str],
    use_shared_overlap_wording: bool = False,
) -> str:
    speed_window = (
        str(
            finding.evidence.focused_speed_band
            if finding.evidence and finding.evidence.focused_speed_band
            else ""
        ).strip()
        or str(finding.strongest_speed_band or "").strip()
    )
    location = display_location(finding.strongest_location, tr=tr)
    signal = candidate_signal_text(finding, tr=tr)
    if use_shared_overlap_wording:
        return tr(
            "REPORT_CANDIDATE_REASON_OVERLAP",
            signal=signal,
            speed=speed_window or tr("UNKNOWN"),
        )
    if finding.weak_spatial_separation:
        return tr(
            "REPORT_CANDIDATE_REASON_WEAK",
            signal=signal,
            speed=speed_window or tr("UNKNOWN"),
        )
    return tr(
        "REPORT_CANDIDATE_REASON_STRONG",
        signal=signal,
        location=location,
        speed=speed_window or tr("UNKNOWN"),
    )


def _path_role_text(index: int, *, tr: Callable[..., str]) -> str:
    if index == 0:
        return tr("REPORT_PATH_ROLE_PRIMARY")
    if index == 1:
        return tr("REPORT_PATH_ROLE_ALTERNATIVE")
    return tr("REPORT_PATH_ROLE_LOW_CONFIDENCE")


def _recapture_issue_lines(
    *,
    aggregate: TestRun,
    primary_candidate_facts: PrimaryReportFacts,
    location_confidence_key: str,
    suitability_checks: Sequence[SuitabilityCheck],
    warnings: Sequence[RunContextWarning],
    lang: str,
    tr: Callable[..., str],
) -> tuple[str, ...]:
    issues: list[str] = []
    if has_source_overlap(aggregate, tr=tr):
        ranked = list(aggregate.effective_top_causes()[:2])
        if len(ranked) > 1:
            append_unique_line(
                issues,
                tr(
                    "REPORT_RECAPTURE_ISSUE_SOURCE_OVERLAP",
                    primary=human_source(ranked[0].suspected_source, tr=tr),
                    alternative=human_source(ranked[1].suspected_source, tr=tr),
                ),
            )
    if location_confidence_key == "weak":
        append_unique_line(issues, tr("REPORT_RECAPTURE_ISSUE_WEAK_LOCATION"))
    elif location_confidence_key == "mixed":
        append_unique_line(issues, tr("REPORT_RECAPTURE_ISSUE_MIXED_LOCATION"))
    if is_transient_primary(primary_candidate_facts):
        append_unique_line(issues, tr("REPORT_RECAPTURE_ISSUE_TRANSIENT"))
    for detail in nonpass_detail_lines(
        suitability_checks=suitability_checks,
        warnings=warnings,
        lang=lang,
        tr=tr,
    ):
        append_unique_line(issues, detail)
    if not issues:
        note = proof_caveat_text(
            primary_candidate_facts=primary_candidate_facts,
            action_status_key="recapture_before_acting",
            location_confidence_key=location_confidence_key,
            tr=tr,
        )
        append_unique_line(issues, note or tr("REPORT_CAPTURE_ISSUE_GENERIC"))
    return tuple(issues[:4])


def _recapture_actions(
    *,
    aggregate: TestRun,
    primary_candidate_facts: PrimaryReportFacts,
    location_confidence_key: str,
    expected_locations: Sequence[str],
    active_locations: Sequence[str],
    suitability_checks: Sequence[SuitabilityCheck],
    warnings: Sequence[RunContextWarning],
    tr: Callable[..., str],
) -> tuple[str, ...]:
    expected = len(expected_locations) or len(active_locations)
    actions: list[str] = []
    if has_source_overlap(aggregate, tr=tr):
        append_unique_line(actions, tr("REPORT_RECAPTURE_ACTION_COMPARE_PATHS"))
    if check_state(suitability_checks, "SUITABILITY_CHECK_SPEED_VARIATION") != "pass":
        append_unique_line(actions, tr("REPORT_RECAPTURE_ACTION_STEADY_HOLD"))
    if is_transient_primary(primary_candidate_facts):
        append_unique_line(actions, tr("REPORT_RECAPTURE_ACTION_REPEAT_EVENT"))
    if (
        location_confidence_key in {"weak", "mixed"}
        or check_state(suitability_checks, "SUITABILITY_CHECK_SENSOR_COVERAGE") != "pass"
    ):
        append_unique_line(actions, tr("TIER_A_CAPTURE_MORE_SENSORS"))
    if (
        primary_candidate_facts.has_reference_gaps
        or check_state(suitability_checks, "SUITABILITY_CHECK_REFERENCE_COMPLETENESS") != "pass"
        or has_warning_code(warnings, "reference_context_incomplete")
    ):
        append_unique_line(actions, tr("TIER_A_CAPTURE_REFERENCE_DATA"))
    if not actions:
        append_unique_line(actions, tr("TIER_A_CAPTURE_WIDER_SPEED"))
        append_unique_line(
            actions,
            tr("REPORT_CAPTURE_CONDITION_FULL_COVERAGE", expected=expected),
        )
    return tuple(actions[:4])


def _recapture_condition_lines(
    *,
    aggregate: TestRun,
    primary_candidate_facts: PrimaryReportFacts,
    location_confidence_key: str,
    expected_locations: Sequence[str],
    active_locations: Sequence[str],
    suitability_checks: Sequence[SuitabilityCheck],
    warnings: Sequence[RunContextWarning],
    tr: Callable[..., str],
) -> tuple[str, ...]:
    expected = len(expected_locations) or len(active_locations)
    lines: list[str] = []
    if check_state(suitability_checks, "SUITABILITY_CHECK_SPEED_VARIATION") != "pass":
        append_unique_line(lines, tr("REPORT_RECAPTURE_CONDITION_STEADY_HOLD"))
    if has_source_overlap(aggregate, tr=tr):
        append_unique_line(lines, tr("REPORT_RECAPTURE_CONDITION_COMPARE_PATHS"))
    if is_transient_primary(primary_candidate_facts):
        append_unique_line(lines, tr("REPORT_RECAPTURE_CONDITION_REPEAT_EVENT"))
    if (
        location_confidence_key in {"weak", "mixed"}
        or check_state(suitability_checks, "SUITABILITY_CHECK_SENSOR_COVERAGE") != "pass"
    ):
        append_unique_line(
            lines,
            tr("REPORT_CAPTURE_CONDITION_FULL_COVERAGE", expected=expected),
        )
    if (
        primary_candidate_facts.has_reference_gaps
        or check_state(suitability_checks, "SUITABILITY_CHECK_REFERENCE_COMPLETENESS") != "pass"
        or has_warning_code(warnings, "reference_context_incomplete")
    ):
        append_unique_line(lines, tr("REPORT_CAPTURE_CONDITION_REFERENCE"))
    if not lines:
        append_unique_line(lines, tr("REPORT_CAPTURE_CONDITION_STEADY"))
        append_unique_line(lines, tr("REPORT_CAPTURE_CONDITION_FULL_COVERAGE", expected=expected))
        append_unique_line(lines, tr("REPORT_CAPTURE_CONDITION_REFERENCE"))
    return tuple(lines[:4])
