"""Recapture guidance assembly for report display facts."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from vibesensor.domain import SuitabilityCheck, TestRun
from vibesensor.report_i18n import human_source
from vibesensor.shared.boundaries.report_interpretation import PrimaryReportFacts
from vibesensor.shared.report_diagnostics import (
    check_state,
    has_warning_code,
    nonpass_detail_lines,
)
from vibesensor.shared.report_presentation import (
    append_unique_line,
    has_source_overlap,
    is_transient_primary,
    proof_caveat_text,
)
from vibesensor.shared.run_context_warning import RunContextWarning

__all__ = [
    "_recapture_actions",
    "_recapture_condition_lines",
    "_recapture_issue_lines",
]


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
