"""Shared ranking helpers for diagnosis findings and top-cause selection."""

from __future__ import annotations

from collections import defaultdict

from ..runlog import as_float_or_none as _as_float
from ._types import Finding

_QUANTISE_STEP = 0.02
_QUANTISE_INV = 1.0 / _QUANTISE_STEP


def finding_sort_key(item: Finding) -> tuple[float, float]:
    """Return a deterministic sort key for findings.

    Confidence is quantised so tiny timing/noise jitter does not reshuffle
    otherwise equivalent findings, leaving the explicit ranking score to break
    ties consistently.
    """
    conf = _as_float(item.get("confidence_0_to_1")) or 0.0
    quantised = round(conf * _QUANTISE_INV) * _QUANTISE_STEP
    rank = _as_float(item.get("_ranking_score")) or 0.0
    return (quantised, rank)


def phase_adjusted_ranking_score(finding: Finding) -> float:
    """Compute the phase-aware score used for top-cause selection."""
    conf = finding.get("confidence_0_to_1")
    confidence = float(conf if conf is not None else 0)
    phase_ev = finding.get("phase_evidence")
    cruise_fraction = (
        float(phase_ev.get("cruise_fraction", 0.0)) if isinstance(phase_ev, dict) else 0.0
    )
    return confidence * (0.85 + 0.15 * cruise_fraction)


def group_findings_by_source(diag_findings: list[Finding]) -> list[tuple[float, Finding]]:
    """Group findings by source and return ranked representatives."""
    groups: dict[str, list[Finding]] = defaultdict(list)
    for finding in diag_findings:
        source = str(finding.get("suspected_source") or "unknown").strip().lower()
        groups[source].append(finding)

    grouped: list[tuple[float, Finding]] = []
    for members in groups.values():
        members_scored = sorted(
            ((phase_adjusted_ranking_score(member), member) for member in members),
            key=lambda item: item[0],
            reverse=True,
        )
        representative: Finding = {**members_scored[0][1]}
        signatures: list[str] = []
        seen_signatures: set[str] = set()
        for _score, member in members_scored:
            signature = str(member.get("frequency_hz_or_order") or "").strip()
            if signature and signature not in seen_signatures:
                signatures.append(signature)
                seen_signatures.add(signature)
        representative["signatures_observed"] = signatures
        representative["grouped_count"] = len(members_scored)
        grouped.append((members_scored[0][0], representative))

    grouped.sort(key=lambda item: item[0], reverse=True)
    return grouped
