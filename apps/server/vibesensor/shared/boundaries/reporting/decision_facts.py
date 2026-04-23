"""Decision-oriented facts for prepared reporting boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.shared.boundaries.reporting.decisions import (
    ActionStatusKey,
    LocationConfidenceKey,
    resolve_action_status_key,
    resolve_alternative_source,
    resolve_location_confidence_key,
)
from vibesensor.shared.boundaries.reporting.projection import (
    PrimaryReportFacts,
    resolve_primary_report_facts,
)
from vibesensor.shared.report_diagnostics import report_suitability_checks, report_warnings

if TYPE_CHECKING:
    from vibesensor.domain import RecommendedAction, SuitabilityCheck, TestRun
    from vibesensor.shared.boundaries.reporting.facts import ReportContextFacts
    from vibesensor.shared.boundaries.reporting.sensor_facts import ReportSensorFacts
    from vibesensor.shared.run_context_warning import RunContextWarning, RunContextWarningsInput

__all__ = [
    "ActionStatusKey",
    "LocationConfidenceKey",
    "ReportDecisionFacts",
    "build_report_decision_facts",
]


@dataclass(frozen=True, slots=True)
class ReportDecisionFacts:
    """Canonical decision-facing report facts for presentation and document assembly."""

    primary_candidate: PrimaryReportFacts
    recommended_actions: tuple[RecommendedAction, ...]
    suitability_checks: tuple[SuitabilityCheck, ...]
    warnings: tuple[RunContextWarning, ...]
    action_status_key: ActionStatusKey
    location_confidence_key: LocationConfidenceKey
    alternative_source: str | None
    alternative_source_visible: bool
    confidence_gap_to_alternative: float | None


def build_report_decision_facts(
    payload: Mapping[str, object],
    *,
    test_run: TestRun,
    origin_location: str,
    sensor_facts: ReportSensorFacts,
    context_facts: ReportContextFacts,
    warnings: RunContextWarningsInput = None,
) -> ReportDecisionFacts:
    """Build decision-facing report facts from canonical run and sensor facts."""

    primary_candidate = resolve_primary_report_facts(
        aggregate=test_run,
        origin_location=origin_location,
        sensor_locations_active=sensor_facts.active_locations,
        sensor_intensity=sensor_facts.active_intensity,
    )
    suitability_checks = report_suitability_checks(test_run.suitability)
    warning_models = _merge_warnings(
        report_warnings(payload, warnings=warnings),
        context_facts.warnings,
    )
    location_confidence_key = resolve_location_confidence_key(
        primary_candidate_facts=primary_candidate,
        coverage_summary=sensor_facts.coverage,
    )
    alternative_source, alternative_source_visible, confidence_gap_to_alternative = (
        resolve_alternative_source(
            test_run,
            primary_candidate_facts=primary_candidate,
        )
    )
    action_status_key = resolve_action_status_key(
        primary_candidate_facts=primary_candidate,
        location_confidence_key=location_confidence_key,
        alternative_source_visible=alternative_source_visible,
        suitability_checks=suitability_checks,
        warnings=warning_models,
    )
    return ReportDecisionFacts(
        primary_candidate=primary_candidate,
        recommended_actions=test_run.recommended_actions,
        suitability_checks=suitability_checks,
        warnings=warning_models,
        action_status_key=action_status_key,
        location_confidence_key=location_confidence_key,
        alternative_source=alternative_source,
        alternative_source_visible=alternative_source_visible,
        confidence_gap_to_alternative=confidence_gap_to_alternative,
    )


def _merge_warnings(
    primary: tuple[RunContextWarning, ...],
    extra: tuple[RunContextWarning, ...],
) -> tuple[RunContextWarning, ...]:
    merged: list[RunContextWarning] = []
    seen_codes: set[str] = set()
    for warning in (*primary, *extra):
        normalized_code = warning.code.strip().lower()
        if normalized_code in seen_codes:
            continue
        seen_codes.add(normalized_code)
        merged.append(warning)
    return tuple(merged)
