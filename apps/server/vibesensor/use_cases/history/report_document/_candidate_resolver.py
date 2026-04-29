"""Primary-candidate resolution helpers for PDF report mapping."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.domain import Finding, TestRun
from vibesensor.shared.boundaries.reporting.confidence_facts import ReportConfidenceFacts
from vibesensor.shared.report_presentation import (
    confidence_reason_text,
    human_source,
    strength_label,
    strength_text,
)

if TYPE_CHECKING:
    from vibesensor.shared.boundaries.reporting.projection import PrimaryReportFacts
    from vibesensor.shared.boundaries.reporting.summary import ReportWholeRunDiagnosisSummary

__all__ = [
    "PrimaryCandidateContext",
    "resolve_primary_report_candidate",
]


@dataclass(frozen=True)
class PrimaryCandidateContext:
    """Primary report candidate resolved from top causes or findings."""

    primary_candidate: Finding | None
    primary_source: object
    primary_system: str
    primary_location: str
    primary_speed: str
    confidence: float
    sensor_count: int
    weak_spatial: bool
    has_reference_gaps: bool
    strength_db: float | None
    strength_text: str
    strength_band_key: str | None
    certainty_key: str
    certainty_label_text: str
    certainty_pct: str
    certainty_reason: str
    tier: str
    dominance_ratio: float | None = None


def resolve_primary_report_candidate(
    *,
    aggregate: TestRun,
    facts: PrimaryReportFacts,
    confidence_facts: ReportConfidenceFacts | None = None,
    diagnosis_summary: ReportWholeRunDiagnosisSummary | None = None,
    tr: Callable[..., str],
    lang: str,
) -> PrimaryCandidateContext:
    """Resolve the primary candidate and all derived certainty fields."""
    primary_candidate = facts.domain_primary or _top_report_candidate(aggregate)
    primary_source = (
        diagnosis_summary.suspected_source if diagnosis_summary else facts.primary_source
    )
    primary_system = human_source(primary_source, tr=tr) if primary_source else tr("UNKNOWN")
    primary_location = (
        diagnosis_summary.dominant_location
        if diagnosis_summary and diagnosis_summary.dominant_location
        else facts.primary_location or tr("UNKNOWN")
    )
    primary_speed = str(
        diagnosis_summary.dominant_speed_band
        if diagnosis_summary and diagnosis_summary.dominant_speed_band
        else facts.primary_speed or tr("UNKNOWN")
    )
    strength_text_value = strength_text(facts.strength_db, lang=lang)
    strength_band_key = (
        strength_label(facts.strength_db)[0] if facts.strength_db is not None else None
    )

    if confidence_facts is not None:
        certainty_key = confidence_facts.label_key
        certainty_label_text = tr(confidence_facts.label_key)
        certainty_pct = confidence_facts.pct_text
        certainty_reason = confidence_reason_text(confidence_facts, tr=tr)
        tier = confidence_facts.tier
    elif facts.domain_primary and facts.domain_primary.confidence_assessment:
        ca = facts.domain_primary.confidence_assessment
        certainty_key = ca.label_key
        certainty_label_text = tr(ca.label_key)
        certainty_pct = ca.pct_text
        certainty_reason = ca.reason
        tier = ca.tier
    else:
        certainty_key = "CONFIDENCE_LOW"
        certainty_label_text = tr("CONFIDENCE_LOW")
        certainty_pct = "0%"
        certainty_reason = ""
        tier = "A"
    return PrimaryCandidateContext(
        primary_candidate=primary_candidate,
        primary_source=primary_source,
        primary_system=primary_system,
        primary_location=primary_location,
        primary_speed=primary_speed,
        confidence=(
            diagnosis_summary.total_score
            if diagnosis_summary and diagnosis_summary.total_score is not None
            else facts.confidence
        ),
        sensor_count=facts.sensor_count,
        weak_spatial=facts.weak_spatial,
        has_reference_gaps=facts.has_reference_gaps,
        strength_db=facts.strength_db,
        strength_text=strength_text_value,
        strength_band_key=strength_band_key,
        dominance_ratio=(
            diagnosis_summary.dominance_ratio
            if diagnosis_summary and diagnosis_summary.dominance_ratio is not None
            else facts.dominance_ratio
        ),
        certainty_key=certainty_key,
        certainty_label_text=certainty_label_text,
        certainty_pct=certainty_pct,
        certainty_reason=certainty_reason,
        tier=tier,
    )


def _top_report_candidate(aggregate: TestRun) -> Finding | None:
    effective = aggregate.effective_top_causes()
    if effective:
        return effective[0]
    non_reference_findings = aggregate.non_reference_findings
    if non_reference_findings:
        return non_reference_findings[0]
    return aggregate.findings[0] if aggregate.findings else None
