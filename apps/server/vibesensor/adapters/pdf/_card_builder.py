"""System-card assembly helpers for PDF report mapping."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from vibesensor.adapters.pdf.pattern_parts import parts_for_pattern
from vibesensor.adapters.pdf.presentation import order_label_human
from vibesensor.adapters.pdf.report_data import (
    PartSuggestion,
    SystemFindingCard,
)
from vibesensor.report_i18n import human_source

if TYPE_CHECKING:
    from vibesensor.adapters.pdf._candidate_resolver import PrimaryCandidateContext
    from vibesensor.adapters.pdf.report_context import ReportMappingContext

__all__ = [
    "build_system_cards",
    "humanize_signatures",
]


def build_system_cards(
    context: ReportMappingContext,
    primary: PrimaryCandidateContext,
    lang: str,
    tr: Callable[..., str],
) -> list[SystemFindingCard]:
    """Build system finding cards for the report template."""
    tier = primary.tier
    if tier == "A":
        return []
    aggregate = context.domain_aggregate
    card_sources = (
        aggregate.effective_top_causes() or aggregate.non_reference_findings or aggregate.findings
    )

    cards: list[SystemFindingCard] = []
    for domain_finding in card_sources[:2]:
        source = str(domain_finding.suspected_source)
        source_human = human_source(source, tr=tr)
        if domain_finding.location and domain_finding.location.is_actionable:
            location = domain_finding.location.display_location
        else:
            location = str(domain_finding.strongest_location or tr("UNKNOWN"))

        if domain_finding.confidence_assessment:
            tone = domain_finding.confidence_assessment.tone
        else:
            tone = domain_finding.confidence_label(
                strength_band_key=primary.strength_band_key,
            )[1]

        signature_values: object
        if domain_finding.signature_labels:
            signature_values = list(domain_finding.signature_labels)
        else:
            signature_values = []
        signatures_human = humanize_signatures(signature_values, lang=lang)
        pattern_text = ", ".join(signatures_human) if signatures_human else tr("UNKNOWN")
        order_label = signatures_human[0] if signatures_human else None
        parts_list = parts_for_pattern(source, order_label, lang=lang)

        card_system_name = source_human
        card_parts = [PartSuggestion(name=part) for part in parts_list]
        if tier == "B":
            card_system_name = f"{source_human} — {tr('TIER_B_HYPOTHESIS_LABEL')}"
            card_parts = []

        cards.append(
            SystemFindingCard(
                system_name=card_system_name,
                strongest_location=location,
                pattern_summary=pattern_text,
                parts=card_parts,
                tone=tone,
            ),
        )
    return cards


def humanize_signatures(signatures: object, *, lang: str) -> list[str]:
    """Localize a short list of order signatures for report display."""
    if not isinstance(signatures, list):
        return []
    return [order_label_human(lang, str(sig)) for sig in signatures[:3]]
