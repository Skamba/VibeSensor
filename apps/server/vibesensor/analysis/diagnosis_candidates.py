"""Shared helpers for filtering and selecting diagnosis candidates.

These utilities are used by both the analysis summary path and the report
mapping path so the same non-reference/actionable selection rules stay in one
place.  Core selection logic (``effective_top_causes``) lives on the domain
aggregate ``RunAnalysisResult``; this module provides boundary-level helpers
that operate on ``FindingPayload`` dicts.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..domain import Finding as DomainFinding
from ._types import FindingPayload, is_finding


def non_reference_findings(items: Sequence[object]) -> list[FindingPayload]:
    """Return well-formed finding dicts excluding ``REF_*`` entries."""
    return [
        item
        for item in items
        if is_finding(item) and not str(item.get("finding_id", "")).upper().startswith("REF_")
    ]


def select_effective_top_causes(
    top_causes: Sequence[object],
    findings: Sequence[object],
) -> tuple[list[FindingPayload], list[FindingPayload], list[FindingPayload], list[FindingPayload]]:
    """Return report-ready cause/finding collections.

    Returns ``(all_findings, findings_non_ref, top_causes_all, effective_top_causes)``.

    The effective top-cause selection mirrors the domain logic on
    ``RunAnalysisResult.effective_top_causes()``, applied to
    ``FindingPayload`` dicts at the serialization boundary.
    """
    all_findings = [item for item in findings if is_finding(item)]
    findings_non_ref = non_reference_findings(all_findings)
    top_causes_all = [item for item in top_causes if is_finding(item)]

    # Materialize domain objects once to avoid repeated from_payload calls
    top_cause_pairs = [(tc, DomainFinding.from_payload(tc)) for tc in top_causes_all]
    top_causes_non_ref = [tc for tc, d in top_cause_pairs if not d.is_reference]
    top_causes_actionable = [
        tc for tc, d in top_cause_pairs if not d.is_reference and d.is_actionable
    ]

    effective_top_causes: list[FindingPayload]
    if top_causes_actionable:
        effective_top_causes = list(top_causes_actionable)
    elif findings_non_ref:
        effective_top_causes = list(findings_non_ref)
    elif top_causes_non_ref:
        effective_top_causes = list(top_causes_non_ref)
    else:
        effective_top_causes = list(top_causes_all)
    return all_findings, findings_non_ref, top_causes_all, effective_top_causes


def normalize_origin_location(location: object) -> str:
    """Normalize the analysis placeholder ``unknown`` to an empty string."""
    normalized = str(location or "").strip()
    return "" if normalized.lower() == "unknown" else normalized
