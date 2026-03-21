"""Primary-candidate resolution helpers for PDF report mapping."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.adapters.pdf.presentation import strength_label, strength_text
from vibesensor.domain import ConfidenceAssessment, Finding
from vibesensor.report_i18n import human_source
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.use_cases.history.report_interpretation import resolve_primary_report_facts

if TYPE_CHECKING:
    from vibesensor.adapters.pdf.report_context import ReportMappingContext

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


def resolve_primary_report_candidate(
    *,
    context: ReportMappingContext,
    sensor_intensity: list[JsonObject],
    tr: Callable[..., str],
    lang: str,
) -> PrimaryCandidateContext:
    """Resolve the primary candidate and all derived certainty fields."""
    primary_candidate = context.top_report_candidate()
    facts = resolve_primary_report_facts(
        aggregate=context.domain_aggregate,
        origin_location=context.origin_location,
        sensor_locations_active=context.sensor_locations_active,
        sensor_intensity=sensor_intensity,
    )
    primary_system = (
        human_source(facts.primary_source, tr=tr) if facts.primary_source else tr("UNKNOWN")
    )
    primary_location = facts.primary_location or tr("UNKNOWN")
    primary_speed = str(facts.primary_speed or tr("UNKNOWN"))
    strength_text_value = strength_text(facts.strength_db, lang=lang)
    strength_band_key = (
        strength_label(facts.strength_db)[0] if facts.strength_db is not None else None
    )

    if facts.domain_primary and facts.domain_primary.confidence_assessment:
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
        tier = ConfidenceAssessment.assess(
            facts.confidence,
            strength_band_key=strength_band_key,
        ).tier
    return PrimaryCandidateContext(
        primary_candidate=primary_candidate,
        primary_source=facts.primary_source,
        primary_system=primary_system,
        primary_location=primary_location,
        primary_speed=primary_speed,
        confidence=facts.confidence,
        sensor_count=facts.sensor_count,
        weak_spatial=facts.weak_spatial,
        has_reference_gaps=facts.has_reference_gaps,
        strength_db=facts.strength_db,
        strength_text=strength_text_value,
        strength_band_key=strength_band_key,
        certainty_key=certainty_key,
        certainty_label_text=certainty_label_text,
        certainty_pct=certainty_pct,
        certainty_reason=certainty_reason,
        tier=tier,
    )
