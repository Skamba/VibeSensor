"""Shared helpers for filtering and selecting diagnosis candidates.

These utilities are used by both the analysis summary path and the report
mapping path so the same non-reference/actionable selection rules stay in one
place.
"""

from __future__ import annotations

from collections.abc import Sequence

from ._types import CandidateFinding, FindingPayload, TopCause, is_finding, is_top_cause

_UNKNOWN_LOCATION_VALUES = {"", "unknown", "not available", "n/a"}
_PLACEHOLDER_SOURCES = {"unknown_resonance", "unknown"}


def non_reference_findings(items: Sequence[object]) -> list[FindingPayload]:
    """Return well-formed finding dicts excluding ``REF_*`` entries."""
    findings = [item for item in items if is_finding(item)]
    return [
        finding
        for finding in findings
        if not str(finding.get("finding_id") or "").strip().upper().startswith("REF_")
    ]


def non_reference_top_causes(items: Sequence[object]) -> list[TopCause]:
    """Return well-formed top-cause dicts excluding ``REF_*`` entries."""
    return [
        cause
        for cause in (item for item in items if is_top_cause(item))
        if not str(cause.get("finding_id") or "").strip().upper().startswith("REF_")
    ]


def is_actionable_location(location: object) -> bool:
    """Whether a strongest-location value contains actionable location data."""
    return str(location or "").strip().lower() not in _UNKNOWN_LOCATION_VALUES


def is_actionable_cause(cause: TopCause) -> bool:
    """Whether a cause is actionable enough to prefer in report rendering."""
    source = str(cause.get("source") or cause.get("suspected_source") or "").strip().lower()
    return source not in _PLACEHOLDER_SOURCES or is_actionable_location(
        cause.get("strongest_location"),
    )


def select_effective_top_causes(
    top_causes: Sequence[object],
    findings: Sequence[object],
) -> tuple[list[FindingPayload], list[FindingPayload], list[TopCause], list[CandidateFinding]]:
    """Return report-ready cause/finding collections.

    Returns ``(all_findings, findings_non_ref, top_causes_all, effective_top_causes)``.
    The effective top-cause list preserves the current preference order:
    actionable non-reference top-causes, then non-reference findings, then
    non-reference top-causes, then all top-causes.
    """
    all_findings = [item for item in findings if is_finding(item)]
    findings_non_ref = non_reference_findings(all_findings)
    top_causes_all = [item for item in top_causes if is_top_cause(item)]
    top_causes_non_ref = non_reference_top_causes(top_causes_all)
    top_causes_actionable = [cause for cause in top_causes_non_ref if is_actionable_cause(cause)]
    effective_top_causes: list[CandidateFinding]
    if top_causes_actionable:
        effective_top_causes = [candidate for candidate in top_causes_actionable]
    elif findings_non_ref:
        effective_top_causes = [candidate for candidate in findings_non_ref]
    elif top_causes_non_ref:
        effective_top_causes = [candidate for candidate in top_causes_non_ref]
    else:
        effective_top_causes = [candidate for candidate in top_causes_all]
    return all_findings, findings_non_ref, top_causes_all, effective_top_causes


def normalize_origin_location(location: object) -> str:
    """Normalize the analysis placeholder ``unknown`` to an empty string."""
    normalized = str(location or "").strip()
    return "" if normalized.lower() == "unknown" else normalized
