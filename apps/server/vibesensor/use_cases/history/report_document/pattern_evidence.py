"""Pattern-evidence builders for PDF report mapping."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from vibesensor.domain import Finding, TestRun, VibrationOrigin
from vibesensor.report_i18n import resolve_i18n
from vibesensor.shared.boundaries.reporting.document import PatternEvidence
from vibesensor.shared.boundaries.reporting.summary import ReportWholeRunDiagnosisSummary
from vibesensor.shared.boundaries.summary_fields.origin import build_origin_explanation
from vibesensor.shared.report_presentation import (
    display_location,
    display_speed_band,
    human_source,
    order_label_human,
)
from vibesensor.use_cases.history.report_document._candidate_resolver import PrimaryCandidateContext
from vibesensor.use_cases.history.report_document.pattern_parts import why_parts_listed

__all__ = [
    "build_pattern_evidence",
    "resolve_interpretation",
    "resolve_parts_context",
]


def build_pattern_evidence(
    *,
    aggregate: TestRun,
    origin: VibrationOrigin | None,
    primary: PrimaryCandidateContext,
    diagnosis_summaries: Sequence[ReportWholeRunDiagnosisSummary],
    lang: str,
    tr: Callable[..., str],
) -> PatternEvidence:
    """Build the pattern-evidence block for the report template."""
    effective = aggregate.effective_top_causes()
    domain_primary = effective[0] if effective else aggregate.primary_finding
    systems_raw = (
        [human_source(summary.suspected_source, tr=tr) for summary in diagnosis_summaries[:3]]
        if diagnosis_summaries
        else [human_source(str(f.suspected_source), tr=tr) for f in effective[:3]]
    )
    systems = list(dict.fromkeys(systems_raw))
    interpretation = resolve_interpretation(origin, lang=lang, tr=tr)
    source_for_why, order_label_for_why = resolve_parts_context(
        primary.primary_candidate,
        domain_finding=domain_primary,
        lang=lang,
    )
    return PatternEvidence(
        matched_systems=systems,
        strongest_location=display_location(primary.primary_location, tr=tr),
        speed_band=display_speed_band(primary.primary_speed, tr=tr),
        strength_label=primary.strength_text,
        strength_peak_db=primary.strength_db,
        certainty_label=primary.certainty_label_text,
        certainty_pct=primary.certainty_pct,
        certainty_reason=primary.certainty_reason,
        warning=primary.certainty_reason if primary.weak_spatial else None,
        interpretation=interpretation or None,
        why_parts_text=why_parts_listed(source_for_why, order_label_for_why, lang=lang),
    )


def resolve_interpretation(origin: VibrationOrigin | None, *, lang: str, tr: Callable) -> str:
    """Resolve the origin explanation into localized report text."""

    if origin is None:
        return ""
    explanation = build_origin_explanation(
        source=str(origin.suspected_source),
        speed_band=display_speed_band(origin.speed_band or "", tr=tr),
        location=origin.summary_location,
        dominance=origin.dominance_ratio,
        weak=origin.weak_spatial_separation,
        dominant_phase=origin.dominant_phase or "",
    )
    return resolve_i18n(lang, explanation, tr=tr)


def resolve_parts_context(
    primary_candidate: Finding | None,
    *,
    domain_finding: Finding | None = None,
    lang: str,
) -> tuple[str, str | None]:
    """Resolve source/order context used for why-parts-listed text."""

    finding = domain_finding or primary_candidate
    if finding is not None:
        source_for_why = str(finding.suspected_source)
        signatures: object = list(finding.signature_labels)
    else:
        source_for_why = ""
        signatures = []
    if isinstance(signatures, list) and signatures:
        order_label = order_label_human(lang, str(signatures[0]))
    else:
        order_label = None
    return source_for_why, order_label
