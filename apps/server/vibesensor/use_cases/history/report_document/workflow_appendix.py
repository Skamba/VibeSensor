"""Appendix-A workflow and recapture builders for report document composition."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from vibesensor.domain import Finding, SuitabilityCheck, TestRun
from vibesensor.report_i18n import human_source
from vibesensor.shared.boundaries.reporting.confidence_facts import ReportConfidenceFacts
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

from .section_context import AppendixAContext, RecaptureAssessment

if TYPE_CHECKING:
    from vibesensor.shared.boundaries.reporting.summary import ReportWholeRunDiagnosisSummary

__all__ = [
    "build_appendix_a_data",
    "build_ranked_candidates",
    "build_recapture_assessment",
]


def build_appendix_a_data(
    *,
    aggregate: TestRun,
    appendix_context: AppendixAContext,
    tr: Callable[..., str],
) -> AppendixAData:
    ranked_candidates = appendix_context.ranked_candidates
    recapture_before_acting = appendix_context.action_status_key == "recapture_before_acting"
    if recapture_before_acting:
        return AppendixAData(
            mode="recapture",
            primary_source=None,
            alternative_source=None,
            why_primary_first=None,
            why_alternative_next=None,
            next_if_clean=None,
            ranked_candidates=[],
            capture_issues=list(appendix_context.recapture.issues),
            capture_changes=list(appendix_context.recapture.actions),
            capture_conditions=list(appendix_context.recapture.conditions),
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
        if appendix_context.alternative_source_visible
        and len(ranked_candidates) > 1
        and ranked_candidates[1].confidence_pct
        else ranked_candidates[1].source_name
        if appendix_context.alternative_source_visible and len(ranked_candidates) > 1
        else None
    )
    return AppendixAData(
        mode="workflow",
        primary_source=primary_source,
        alternative_source=alternative_source,
        why_primary_first=ranked_candidates[0].reason if ranked_candidates else None,
        why_alternative_next=(
            ranked_candidates[1].reason
            if appendix_context.alternative_source_visible and len(ranked_candidates) > 1
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
    diagnosis_summaries: Sequence[ReportWholeRunDiagnosisSummary] = (),
    tr: Callable[..., str],
) -> tuple[RankedCandidateRow, ...]:
    if diagnosis_summaries and not diagnosis_summaries[0].uses_summary_fallback:
        return tuple(
            _ranked_candidate_row_from_diagnosis_summary(
                aggregate,
                summary=summary,
                index=index,
                tr=tr,
            )
            for index, summary in enumerate(diagnosis_summaries[:3])
        )
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


def _ranked_candidate_row_from_diagnosis_summary(
    aggregate: TestRun,
    *,
    summary: ReportWholeRunDiagnosisSummary,
    index: int,
    tr: Callable[..., str],
) -> RankedCandidateRow:
    matched_finding = _finding_for_diagnosis_summary(aggregate, summary=summary)
    inspect_first = (
        display_location(summary.dominant_location, tr=tr)
        if summary.dominant_location
        else (
            display_location(matched_finding.strongest_location, tr=tr)
            if matched_finding is not None
            else tr("UNKNOWN")
        )
    )
    return RankedCandidateRow(
        source_name=human_source(summary.suspected_source, tr=tr),
        confidence_pct=(
            f"{max(0.0, summary.total_score or 0.0) * 100:.0f}%"
            if summary.total_score is not None
            else ""
        ),
        inspect_first=inspect_first,
        path_role=f"{index + 1}. {_path_role_text(index, tr=tr)}",
        reason=_diagnosis_summary_reason_text(summary, matched_finding=matched_finding, tr=tr),
    )


def build_recapture_assessment(
    *,
    aggregate: TestRun,
    primary_candidate_facts: PrimaryReportFacts,
    confidence_facts: ReportConfidenceFacts,
    location_confidence_key: str,
    expected_locations: Sequence[str],
    active_locations: Sequence[str],
    suitability_checks: Sequence[SuitabilityCheck],
    warnings: Sequence[RunContextWarning],
    lang: str,
    tr: Callable[..., str],
) -> RecaptureAssessment:
    expected = len(expected_locations) or len(active_locations)
    source_overlap = has_source_overlap(aggregate, tr=tr)
    weak_location = location_confidence_key == "weak"
    mixed_location = location_confidence_key == "mixed"
    transient_primary = is_transient_primary(primary_candidate_facts)
    speed_variation_nonpass = (
        check_state(suitability_checks, "SUITABILITY_CHECK_SPEED_VARIATION") != "pass"
    )
    sensor_coverage_nonpass = (
        weak_location
        or mixed_location
        or check_state(suitability_checks, "SUITABILITY_CHECK_SENSOR_COVERAGE") != "pass"
    )
    reference_incomplete = (
        primary_candidate_facts.has_reference_gaps
        or check_state(suitability_checks, "SUITABILITY_CHECK_REFERENCE_COMPLETENESS") != "pass"
        or has_warning_code(warnings, "reference_context_incomplete")
    )
    diagnostic_details = tuple(
        nonpass_detail_lines(
            suitability_checks=suitability_checks,
            warnings=warnings,
            lang=lang,
            tr=tr,
        )
    )

    issues: list[str] = []
    if source_overlap:
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
    if weak_location:
        append_unique_line(issues, tr("REPORT_RECAPTURE_ISSUE_WEAK_LOCATION"))
    elif mixed_location:
        append_unique_line(issues, tr("REPORT_RECAPTURE_ISSUE_MIXED_LOCATION"))
    if transient_primary:
        append_unique_line(issues, tr("REPORT_RECAPTURE_ISSUE_TRANSIENT"))
    for detail in diagnostic_details:
        append_unique_line(issues, detail)
    if not issues:
        note = proof_caveat_text(
            confidence_facts=confidence_facts,
            action_status_key="recapture_before_acting",
            location_confidence_key=location_confidence_key,
            tr=tr,
        )
        append_unique_line(issues, note or tr("REPORT_CAPTURE_ISSUE_GENERIC"))

    actions: list[str] = []
    if source_overlap:
        append_unique_line(actions, tr("REPORT_RECAPTURE_ACTION_COMPARE_PATHS"))
    if speed_variation_nonpass:
        append_unique_line(actions, tr("REPORT_RECAPTURE_ACTION_STEADY_HOLD"))
    if transient_primary:
        append_unique_line(actions, tr("REPORT_RECAPTURE_ACTION_REPEAT_EVENT"))
    if sensor_coverage_nonpass:
        append_unique_line(actions, tr("TIER_A_CAPTURE_MORE_SENSORS"))
    if reference_incomplete:
        append_unique_line(actions, tr("TIER_A_CAPTURE_REFERENCE_DATA"))
    if not actions:
        append_unique_line(actions, tr("TIER_A_CAPTURE_WIDER_SPEED"))
        append_unique_line(
            actions,
            tr("REPORT_CAPTURE_CONDITION_FULL_COVERAGE", expected=expected),
        )

    conditions: list[str] = []
    if speed_variation_nonpass:
        append_unique_line(conditions, tr("REPORT_RECAPTURE_CONDITION_STEADY_HOLD"))
    if source_overlap:
        append_unique_line(conditions, tr("REPORT_RECAPTURE_CONDITION_COMPARE_PATHS"))
    if transient_primary:
        append_unique_line(conditions, tr("REPORT_RECAPTURE_CONDITION_REPEAT_EVENT"))
    if sensor_coverage_nonpass:
        append_unique_line(
            conditions,
            tr("REPORT_CAPTURE_CONDITION_FULL_COVERAGE", expected=expected),
        )
    if reference_incomplete:
        append_unique_line(conditions, tr("REPORT_CAPTURE_CONDITION_REFERENCE"))
    if not conditions:
        append_unique_line(conditions, tr("REPORT_CAPTURE_CONDITION_STEADY"))
        append_unique_line(
            conditions,
            tr("REPORT_CAPTURE_CONDITION_FULL_COVERAGE", expected=expected),
        )
        append_unique_line(conditions, tr("REPORT_CAPTURE_CONDITION_REFERENCE"))

    return RecaptureAssessment(
        issues=tuple(issues[:4]),
        actions=tuple(actions[:4]),
        conditions=tuple(conditions[:4]),
    )


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


def _finding_for_diagnosis_summary(
    aggregate: TestRun,
    *,
    summary: ReportWholeRunDiagnosisSummary,
) -> Finding | None:
    for finding in aggregate.effective_top_causes():
        if str(finding.suspected_source) == summary.suspected_source:
            return finding
    for finding in aggregate.findings:
        if str(finding.suspected_source) == summary.suspected_source:
            return finding
    return None


def _diagnosis_summary_reason_text(
    summary: ReportWholeRunDiagnosisSummary,
    *,
    matched_finding: Finding | None,
    tr: Callable[..., str],
) -> str:
    if summary.supporting_duration_s is not None and summary.supporting_window_count is not None:
        return tr(
            "REPORT_SUPPORT_WINDOW_SUMMARY_FULL",
            count=str(summary.supporting_window_count),
            duration=f"{summary.supporting_duration_s:.1f}",
        )
    if summary.supporting_window_count is not None and summary.supporting_window_count > 0:
        return tr(
            "REPORT_SUPPORT_WINDOW_SUMMARY_COUNT_ONLY",
            count=str(summary.supporting_window_count),
        )
    if matched_finding is not None:
        return _candidate_reason_text(matched_finding, tr=tr)
    return tr("REPORT_SIGNAL_FALLBACK")


def _path_role_text(index: int, *, tr: Callable[..., str]) -> str:
    if index == 0:
        return tr("REPORT_PATH_ROLE_PRIMARY")
    if index == 1:
        return tr("REPORT_PATH_ROLE_ALTERNATIVE")
    return tr("REPORT_PATH_ROLE_LOW_CONFIDENCE")
