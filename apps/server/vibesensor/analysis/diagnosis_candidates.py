"""Boundary helpers for filtering and selecting diagnosis candidates.

These utilities bridge between the serialization-oriented
``FindingPayload`` dicts and the domain aggregate
``TestRun``.  All selection logic is **delegated** to the
domain aggregate's ``effective_top_causes()`` method — this module
does not duplicate the selection rules.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..boundaries.finding import finding_from_payload
from ..domain import ConfigurationSnapshot, Run, TestRun
from ._types import FindingPayload, is_finding


def non_reference_findings(items: Sequence[object]) -> list[FindingPayload]:
    """Return well-formed finding dicts excluding reference entries.

    Delegates classification to domain ``Finding.is_reference`` so the
    reference-detection rule has a single source of truth.
    """
    return [
        item for item in items if is_finding(item) and not finding_from_payload(item).is_reference
    ]


def select_effective_top_causes(
    top_causes: Sequence[object],
    findings: Sequence[object],
) -> tuple[list[FindingPayload], list[FindingPayload], list[FindingPayload], list[FindingPayload]]:
    """Return report-ready cause/finding collections.

    Returns ``(all_findings, findings_non_ref, top_causes_all, effective_top_causes)``.

    Selection logic delegates to ``TestRun.effective_top_causes()``
    so the decision rules have a single source of truth in the domain
    aggregate.
    """
    all_findings = [item for item in findings if is_finding(item)]
    findings_non_ref = non_reference_findings(all_findings)
    top_causes_all = [item for item in top_causes if is_finding(item)]

    # Build domain objects and delegate selection to the domain aggregate
    domain_findings = tuple(finding_from_payload(f) for f in all_findings)
    domain_top_causes = tuple(finding_from_payload(tc) for tc in top_causes_all)

    aggregate = TestRun(
        run=Run(run_id="boundary"),
        configuration_snapshot=ConfigurationSnapshot(),
        findings=domain_findings,
        top_causes=domain_top_causes,
    )
    effective_domain = aggregate.effective_top_causes()
    effective_ids = {f.finding_id for f in effective_domain}

    # Map the domain selection back to payloads, preserving order.
    # effective_top_causes may return items from top_causes or findings,
    # so check both sources.
    effective: list[FindingPayload] = []
    seen: set[str] = set()
    for tc in top_causes_all:
        fid = str(tc.get("finding_id", ""))
        if fid in effective_ids and fid not in seen:
            effective.append(tc)
            seen.add(fid)
    for f in all_findings:
        fid = str(f.get("finding_id", ""))
        if fid in effective_ids and fid not in seen:
            effective.append(f)
            seen.add(fid)

    return all_findings, findings_non_ref, top_causes_all, effective


def normalize_origin_location(location: object) -> str:
    """Normalize the analysis placeholder ``unknown`` to an empty string."""
    normalized = str(location or "").strip()
    return "" if normalized.lower() == "unknown" else normalized
