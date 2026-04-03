"""Decision logic for prepared history report facts."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from vibesensor.domain import Finding, SuitabilityCheck, TestRun
from vibesensor.shared.boundaries.report_interpretation import PrimaryReportFacts
from vibesensor.shared.run_context_warning import RunContextWarning

from .report_fact_coverage import ReportCoverageSummary, primary_location_has_coverage_gap

type LocationConfidenceKey = Literal["weak", "mixed", "strong"]
type ActionStatusKey = Literal["recapture_before_acting", "action_ready_caution", "action_ready"]

__all__ = [
    "ActionStatusKey",
    "LocationConfidenceKey",
    "resolve_action_status_key",
    "resolve_alternative_source",
    "resolve_location_confidence_key",
]


def resolve_location_confidence_key(
    *,
    primary_candidate_facts: PrimaryReportFacts,
    coverage_summary: ReportCoverageSummary,
) -> LocationConfidenceKey:
    """Resolve one typed location-confidence bucket for the report."""

    hotspot = primary_candidate_facts.location_hotspot
    dominance_ratio = primary_candidate_facts.dominance_ratio
    primary_gap = primary_location_has_coverage_gap(
        primary_candidate_facts.primary_location,
        coverage_summary,
    )
    if primary_candidate_facts.weak_spatial or primary_gap:
        return "weak"
    if dominance_ratio is not None:
        if dominance_ratio < 1.25:
            return "weak"
        if dominance_ratio < 1.75 or bool(coverage_summary.partial_locations):
            return "mixed"
        return "strong"
    if hotspot is not None and hotspot.localization_confidence is not None:
        if hotspot.localization_confidence < 0.4:
            return "weak"
        if hotspot.localization_confidence < 0.7 or bool(coverage_summary.partial_locations):
            return "mixed"
        return "strong"
    return "mixed"


def _relevant_source_candidates(aggregate: TestRun) -> tuple[Finding, ...]:
    return aggregate.effective_top_causes() or aggregate.non_reference_findings


def resolve_alternative_source(
    aggregate: TestRun,
    *,
    primary_candidate_facts: PrimaryReportFacts,
) -> tuple[str | None, bool, float | None]:
    """Resolve the visible alternative source and its confidence gap."""

    candidates = _relevant_source_candidates(aggregate)
    primary = primary_candidate_facts.domain_primary
    if primary is None:
        return None, False, None
    primary_source = str(primary.suspected_source).strip().lower()
    primary_conf = primary.effective_confidence
    ambiguity_visible = bool(
        primary_candidate_facts.weak_spatial
        or (
            primary_candidate_facts.location_hotspot is not None
            and primary_candidate_facts.location_hotspot.ambiguous
        )
    )
    for candidate in candidates[1:]:
        source = str(candidate.suspected_source).strip().lower()
        if not source or source == primary_source:
            continue
        confidence_gap = max(0.0, primary_conf - candidate.effective_confidence)
        visible = confidence_gap <= 0.20 or ambiguity_visible
        return str(candidate.suspected_source), visible, confidence_gap
    return None, False, None


def _is_blocking_suitability(check: SuitabilityCheck) -> bool:
    key = check.check_key.strip().upper()
    state = check.state.strip().lower()
    if state in {"fail", "error"}:
        return True
    return (
        key
        in {
            "SUITABILITY_CHECK_SENSOR_COVERAGE",
            "SUITABILITY_CHECK_FRAME_INTEGRITY",
        }
        and state != "pass"
    )


def _has_nonblocking_caution_signals(
    *,
    suitability_checks: Sequence[SuitabilityCheck],
    warnings: Sequence[RunContextWarning],
) -> bool:
    if any(warning.severity.strip().lower() in {"warn", "error"} for warning in warnings):
        return True
    return any(check.state.strip().lower() != "pass" for check in suitability_checks)


def _allows_system_level_caution_with_weak_location(
    *,
    primary_candidate_facts: PrimaryReportFacts,
) -> bool:
    primary = primary_candidate_facts.domain_primary
    if (
        primary is None
        or primary.confidence_assessment is None
        or not primary_candidate_facts.weak_spatial
    ):
        return False
    source_key = (
        str(primary_candidate_facts.primary_source or primary.suspected_source).strip().lower()
    )
    if source_key not in {"engine", "driveline"}:
        return False
    return primary.confidence_assessment.tier in {"B", "C"}


def resolve_action_status_key(
    *,
    primary_candidate_facts: PrimaryReportFacts,
    location_confidence_key: LocationConfidenceKey,
    alternative_source_visible: bool,
    suitability_checks: Sequence[SuitabilityCheck],
    warnings: Sequence[RunContextWarning],
) -> ActionStatusKey:
    """Resolve the typed action-status bucket for report display."""

    primary = primary_candidate_facts.domain_primary
    if primary is None or primary_candidate_facts.primary_source is None:
        return "recapture_before_acting"
    tier = primary.confidence_assessment.tier if primary.confidence_assessment is not None else "A"
    weak_location_caution = (
        location_confidence_key == "weak"
        and _allows_system_level_caution_with_weak_location(
            primary_candidate_facts=primary_candidate_facts,
        )
    )
    if (
        tier == "A"
        or (location_confidence_key == "weak" and not weak_location_caution)
        or primary_candidate_facts.has_reference_gaps
        or any(_is_blocking_suitability(check) for check in suitability_checks)
    ):
        return "recapture_before_acting"
    if (
        tier == "B"
        or location_confidence_key == "mixed"
        or weak_location_caution
        or alternative_source_visible
        or _has_nonblocking_caution_signals(
            suitability_checks=suitability_checks,
            warnings=warnings,
        )
    ):
        return "action_ready_caution"
    return "action_ready"
