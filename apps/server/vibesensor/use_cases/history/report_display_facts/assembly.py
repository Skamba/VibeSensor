"""Prepared report display-fact orchestration."""

from __future__ import annotations

from collections.abc import Sequence

from vibesensor.domain import LocationIntensitySummary, SuitabilityCheck, TestRun
from vibesensor.report_i18n import tr as _tr
from vibesensor.shared.boundaries.report_interpretation import PrimaryReportFacts
from vibesensor.shared.report_presentation import (
    coverage_label,
    coverage_notes,
    proof_caveat_text,
    runner_up_corner,
)
from vibesensor.shared.run_context_warning import RunContextWarning
from vibesensor.shared.types.json_types import JsonValue

from .appendix_display import build_appendix_a_display, build_appendix_b_display
from .candidate_display import build_ranked_candidates
from .models import PreparedReportDisplayFacts
from .recapture import (
    _recapture_actions,
    _recapture_condition_lines,
    _recapture_issue_lines,
)
from .verdict_display import build_verdict_display

__all__ = ["prepare_report_display_facts"]


def prepare_report_display_facts(
    *,
    aggregate: TestRun,
    primary_candidate_facts: PrimaryReportFacts,
    active_sensor_intensity: Sequence[LocationIntensitySummary],
    duration_text: str | None,
    action_status_key: str,
    location_confidence_key: str,
    alternative_source_visible: bool,
    expected_locations: Sequence[str],
    active_locations: Sequence[str],
    missing_locations: Sequence[str],
    partial_locations: Sequence[str],
    suitability_checks: Sequence[SuitabilityCheck],
    warnings: Sequence[RunContextWarning],
    lang: str,
) -> PreparedReportDisplayFacts:
    def tr(key: str, **kw: JsonValue) -> str:
        return str(_tr(lang, key, **kw))

    resolved_coverage_label = coverage_label(
        expected_locations=expected_locations,
        active_locations=active_locations,
        missing_locations=missing_locations,
        partial_locations=partial_locations,
        tr=tr,
    )
    resolved_coverage_notes = coverage_notes(
        missing_locations=missing_locations,
        partial_locations=partial_locations,
        tr=tr,
    )
    resolved_runner_up_corner = runner_up_corner(active_sensor_intensity, tr=tr)
    proof_caveat = proof_caveat_text(
        primary_candidate_facts=primary_candidate_facts,
        action_status_key=action_status_key,
        location_confidence_key=location_confidence_key,
        tr=tr,
    )
    ranked_candidates = build_ranked_candidates(aggregate, tr=tr)
    recapture_issues = _recapture_issue_lines(
        aggregate=aggregate,
        primary_candidate_facts=primary_candidate_facts,
        location_confidence_key=location_confidence_key,
        suitability_checks=suitability_checks,
        warnings=warnings,
        lang=lang,
        tr=tr,
    )
    recapture_actions = _recapture_actions(
        aggregate=aggregate,
        primary_candidate_facts=primary_candidate_facts,
        location_confidence_key=location_confidence_key,
        expected_locations=expected_locations,
        active_locations=active_locations,
        suitability_checks=suitability_checks,
        warnings=warnings,
        tr=tr,
    )
    recapture_conditions = _recapture_condition_lines(
        aggregate=aggregate,
        primary_candidate_facts=primary_candidate_facts,
        location_confidence_key=location_confidence_key,
        expected_locations=expected_locations,
        active_locations=active_locations,
        suitability_checks=suitability_checks,
        warnings=warnings,
        tr=tr,
    )
    verdict = build_verdict_display(
        aggregate=aggregate,
        primary_candidate_facts=primary_candidate_facts,
        duration_text=duration_text,
        action_status_key=action_status_key,
        location_confidence_key=location_confidence_key,
        alternative_source_visible=alternative_source_visible,
        active_locations=active_locations,
        coverage_label=resolved_coverage_label,
        runner_up_corner=resolved_runner_up_corner,
        proof_caveat=proof_caveat,
        recapture_issues=recapture_issues,
        suitability_checks=suitability_checks,
        warnings=warnings,
        lang=lang,
        tr=tr,
    )
    appendix_a = build_appendix_a_display(
        aggregate=aggregate,
        action_status_key=action_status_key,
        alternative_source_visible=alternative_source_visible,
        ranked_candidates=ranked_candidates,
        recapture_issues=recapture_issues,
        recapture_actions=recapture_actions,
        recapture_conditions=recapture_conditions,
        tr=tr,
    )
    appendix_b = build_appendix_b_display(
        primary_candidate_facts=primary_candidate_facts,
        action_status_key=action_status_key,
        location_confidence_key=location_confidence_key,
        runner_up_corner=resolved_runner_up_corner,
        coverage_label=resolved_coverage_label,
        coverage_notes=resolved_coverage_notes,
        tr=tr,
    )
    return PreparedReportDisplayFacts(
        verdict=verdict,
        appendix_a=appendix_a,
        appendix_b=appendix_b,
    )
