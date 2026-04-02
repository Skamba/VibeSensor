"""Recapture guidance assembly for report display facts."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from vibesensor.domain import TestRun
from vibesensor.report_i18n import human_source
from vibesensor.shared.boundaries.report_interpretation import PrimaryReportFacts
from vibesensor.shared.types.history_analysis_contracts import RunSuitabilityCheck
from vibesensor.shared.types.history_analysis_contracts import (
    SummaryWarningResponse as SummaryWarningPayload,
)

from .shared import (
    _append_unique_line,
    _check_state,
    _has_source_overlap,
    _has_warning_code,
    _is_transient_primary,
    _nonpass_detail_lines,
    _proof_caveat_text,
)

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
    suitability_checks: Sequence[RunSuitabilityCheck],
    warnings: Sequence[SummaryWarningPayload],
    lang: str,
    tr: Callable[..., str],
) -> tuple[str, ...]:
    issues: list[str] = []
    if _has_source_overlap(aggregate, tr=tr):
        ranked = list(aggregate.effective_top_causes()[:2])
        if len(ranked) > 1:
            _append_unique_line(
                issues,
                tr(
                    "REPORT_RECAPTURE_ISSUE_SOURCE_OVERLAP",
                    primary=human_source(ranked[0].suspected_source, tr=tr),
                    alternative=human_source(ranked[1].suspected_source, tr=tr),
                ),
            )
    if location_confidence_key == "weak":
        _append_unique_line(issues, tr("REPORT_RECAPTURE_ISSUE_WEAK_LOCATION"))
    elif location_confidence_key == "mixed":
        _append_unique_line(issues, tr("REPORT_RECAPTURE_ISSUE_MIXED_LOCATION"))
    if _is_transient_primary(primary_candidate_facts):
        _append_unique_line(issues, tr("REPORT_RECAPTURE_ISSUE_TRANSIENT"))
    for detail in _nonpass_detail_lines(
        suitability_checks=suitability_checks,
        warnings=warnings,
        lang=lang,
        tr=tr,
    ):
        _append_unique_line(issues, detail)
    if not issues:
        note = _proof_caveat_text(
            primary_candidate_facts=primary_candidate_facts,
            action_status_key="recapture_before_acting",
            location_confidence_key=location_confidence_key,
            tr=tr,
        )
        _append_unique_line(issues, note or tr("REPORT_CAPTURE_ISSUE_GENERIC"))
    return tuple(issues[:4])


def _recapture_actions(
    *,
    aggregate: TestRun,
    primary_candidate_facts: PrimaryReportFacts,
    location_confidence_key: str,
    expected_locations: Sequence[str],
    active_locations: Sequence[str],
    suitability_checks: Sequence[RunSuitabilityCheck],
    warnings: Sequence[SummaryWarningPayload],
    tr: Callable[..., str],
) -> tuple[str, ...]:
    expected = len(expected_locations) or len(active_locations)
    actions: list[str] = []
    if _has_source_overlap(aggregate, tr=tr):
        _append_unique_line(actions, tr("REPORT_RECAPTURE_ACTION_COMPARE_PATHS"))
    if _check_state(suitability_checks, "SUITABILITY_CHECK_SPEED_VARIATION") != "pass":
        _append_unique_line(actions, tr("REPORT_RECAPTURE_ACTION_STEADY_HOLD"))
    if _is_transient_primary(primary_candidate_facts):
        _append_unique_line(actions, tr("REPORT_RECAPTURE_ACTION_REPEAT_EVENT"))
    if (
        location_confidence_key in {"weak", "mixed"}
        or _check_state(suitability_checks, "SUITABILITY_CHECK_SENSOR_COVERAGE") != "pass"
    ):
        _append_unique_line(actions, tr("TIER_A_CAPTURE_MORE_SENSORS"))
    if (
        primary_candidate_facts.has_reference_gaps
        or _check_state(suitability_checks, "SUITABILITY_CHECK_REFERENCE_COMPLETENESS") != "pass"
        or _has_warning_code(warnings, "reference_context_incomplete")
    ):
        _append_unique_line(actions, tr("TIER_A_CAPTURE_REFERENCE_DATA"))
    if not actions:
        _append_unique_line(actions, tr("TIER_A_CAPTURE_WIDER_SPEED"))
        _append_unique_line(
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
    suitability_checks: Sequence[RunSuitabilityCheck],
    warnings: Sequence[SummaryWarningPayload],
    tr: Callable[..., str],
) -> tuple[str, ...]:
    expected = len(expected_locations) or len(active_locations)
    lines: list[str] = []
    if _check_state(suitability_checks, "SUITABILITY_CHECK_SPEED_VARIATION") != "pass":
        _append_unique_line(lines, tr("REPORT_RECAPTURE_CONDITION_STEADY_HOLD"))
    if _has_source_overlap(aggregate, tr=tr):
        _append_unique_line(lines, tr("REPORT_RECAPTURE_CONDITION_COMPARE_PATHS"))
    if _is_transient_primary(primary_candidate_facts):
        _append_unique_line(lines, tr("REPORT_RECAPTURE_CONDITION_REPEAT_EVENT"))
    if (
        location_confidence_key in {"weak", "mixed"}
        or _check_state(suitability_checks, "SUITABILITY_CHECK_SENSOR_COVERAGE") != "pass"
    ):
        _append_unique_line(
            lines,
            tr("REPORT_CAPTURE_CONDITION_FULL_COVERAGE", expected=expected),
        )
    if (
        primary_candidate_facts.has_reference_gaps
        or _check_state(suitability_checks, "SUITABILITY_CHECK_REFERENCE_COMPLETENESS") != "pass"
        or _has_warning_code(warnings, "reference_context_incomplete")
    ):
        _append_unique_line(lines, tr("REPORT_CAPTURE_CONDITION_REFERENCE"))
    if not lines:
        _append_unique_line(lines, tr("REPORT_CAPTURE_CONDITION_STEADY"))
        _append_unique_line(lines, tr("REPORT_CAPTURE_CONDITION_FULL_COVERAGE", expected=expected))
        _append_unique_line(lines, tr("REPORT_CAPTURE_CONDITION_REFERENCE"))
    return tuple(lines[:4])
