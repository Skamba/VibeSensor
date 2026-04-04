"""Appendix-A workflow and recapture builders for report document composition."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from vibesensor.domain import Finding, SuitabilityCheck, TestRun
from vibesensor.report_i18n import human_source
from vibesensor.shared.boundaries.reporting.document import AppendixAData, RankedCandidateRow
from vibesensor.shared.boundaries.reporting.projection import PrimaryReportFacts
from vibesensor.shared.report_diagnostics import check_state, has_warning_code, nonpass_detail_lines
from vibesensor.shared.report_presentation import (
    append_unique_line,
    candidate_signal_text,
    confidence_pct_text,
    display_location,
    has_source_overlap,
    is_transient_primary,
    proof_caveat_text,
    uses_shared_overlap_wording,
)
from vibesensor.shared.run_context_warning import RunContextWarning

__all__ = [
    "build_appendix_a_data",
    "build_ranked_candidates",
    "recapture_actions",
    "recapture_condition_lines",
    "recapture_issue_lines",
]


def build_appendix_a_data(
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


def build_ranked_candidates(
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


def recapture_issue_lines(
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


def recapture_actions(
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


def recapture_condition_lines(
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
