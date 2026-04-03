"""Appendix display builders for report display facts."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from vibesensor.domain import TestRun
from vibesensor.shared.boundaries.report_interpretation import PrimaryReportFacts
from vibesensor.shared.report_presentation import (
    display_location,
    location_confidence_text,
    presented_location_confidence_key,
)

from .candidate_display import next_if_primary_clean
from .models import (
    PreparedAppendixADisplay,
    PreparedAppendixBSummaryDisplay,
    PreparedRankedCandidateDisplay,
)

__all__ = [
    "build_appendix_a_display",
    "build_appendix_b_display",
]


def build_appendix_a_display(
    *,
    aggregate: TestRun,
    action_status_key: str,
    alternative_source_visible: bool,
    ranked_candidates: Sequence[PreparedRankedCandidateDisplay],
    recapture_issues: Sequence[str],
    recapture_actions: Sequence[str],
    recapture_conditions: Sequence[str],
    tr: Callable[..., str],
) -> PreparedAppendixADisplay:
    recapture_before_acting = action_status_key == "recapture_before_acting"
    if recapture_before_acting:
        return PreparedAppendixADisplay(
            mode="recapture",
            primary_source=None,
            alternative_source=None,
            why_primary_first=None,
            why_alternative_next=None,
            next_if_clean=None,
            ranked_candidates=(),
            capture_issues=tuple(recapture_issues),
            capture_changes=tuple(recapture_actions),
            capture_conditions=tuple(recapture_conditions),
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
    return PreparedAppendixADisplay(
        mode="workflow",
        primary_source=primary_source,
        alternative_source=alternative_source,
        why_primary_first=ranked_candidates[0].reason if ranked_candidates else None,
        why_alternative_next=(
            ranked_candidates[1].reason
            if alternative_source_visible and len(ranked_candidates) > 1
            else None
        ),
        next_if_clean=next_if_primary_clean(aggregate, tr=tr),
        ranked_candidates=tuple(ranked_candidates),
        capture_issues=(),
        capture_changes=(),
        capture_conditions=(),
    )


def build_appendix_b_display(
    *,
    primary_candidate_facts: PrimaryReportFacts,
    action_status_key: str,
    location_confidence_key: str,
    runner_up_corner: str | None,
    coverage_label: str,
    coverage_notes: Sequence[str],
    tr: Callable[..., str],
) -> PreparedAppendixBSummaryDisplay:
    dominance_ratio_text = (
        tr(
            "REPORT_DOMINANCE_RATIO_TEXT",
            ratio=f"{primary_candidate_facts.dominance_ratio:.2f}",
        )
        if primary_candidate_facts.dominance_ratio is not None
        else tr("REPORT_DOMINANCE_RATIO_UNKNOWN")
    )
    return PreparedAppendixBSummaryDisplay(
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
        coverage_notes=tuple(coverage_notes),
    )
