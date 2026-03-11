"""Top-cause selection, ranking helpers, and confidence presentation.

Ranking helpers (``finding_sort_key``, ``phase_adjusted_ranking_score``,
``group_findings_by_source``) were previously in a separate ``ranking``
module but merged here because this module is their primary consumer and
no other production module needs them independently.
"""

from __future__ import annotations

import math
from collections import defaultdict

from ..constants import ORDER_MIN_CONFIDENCE
from ..domain_models import as_float_or_none as _as_float
from ._types import Finding, TopCause
from .strength_labels import (
    CONFIDENCE_HIGH_THRESHOLD,
    CONFIDENCE_MEDIUM_THRESHOLD,
)

# ---------------------------------------------------------------------------
# Ranking helpers
# ---------------------------------------------------------------------------

_QUANTISE_STEP = 0.02
_QUANTISE_INV = 1.0 / _QUANTISE_STEP


def finding_sort_key(item: Finding) -> tuple[float, float]:
    """Return a deterministic sort key for findings.

    Confidence is quantised so tiny timing/noise jitter does not reshuffle
    otherwise equivalent findings, leaving the explicit ranking score to break
    ties consistently.
    """
    conf = _as_float(item.get("confidence")) or 0.0
    quantised = round(conf * _QUANTISE_INV) * _QUANTISE_STEP
    rank = _as_float(item.get("_ranking_score")) or 0.0
    return (quantised, rank)


def phase_adjusted_ranking_score(finding: Finding) -> float:
    """Compute the phase-aware score used for top-cause selection."""
    conf = finding.get("confidence")
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


# ---------------------------------------------------------------------------
# Confidence and top-cause selection
# ---------------------------------------------------------------------------


def confidence_label(
    conf_0_to_1: float | None,
    *,
    strength_band_key: str | None = None,
) -> tuple[str, str, str]:
    """Return ``(label_key, tone, pct_text)`` for a 0–1 confidence value."""
    conf = float(conf_0_to_1) if conf_0_to_1 is not None else 0.0
    if not math.isfinite(conf):
        conf = 0.0
    pct = max(0.0, min(100.0, conf * 100.0))
    pct_text = f"{pct:.0f}%"
    if conf >= CONFIDENCE_HIGH_THRESHOLD:
        label_key, tone = "CONFIDENCE_HIGH", "success"
    elif conf >= CONFIDENCE_MEDIUM_THRESHOLD:
        label_key, tone = "CONFIDENCE_MEDIUM", "warn"
    else:
        label_key, tone = "CONFIDENCE_LOW", "neutral"
    if (strength_band_key or "").strip().lower() == "negligible" and label_key == "CONFIDENCE_HIGH":
        label_key, tone = "CONFIDENCE_MEDIUM", "warn"
    return label_key, tone, pct_text


def select_top_causes(
    findings: list[Finding],
    *,
    drop_off_points: float = 15.0,
    max_causes: int = 3,
    strength_band_key: str | None = None,
) -> list[TopCause]:
    """Group findings by source, rank the strongest group per source, and trim by drop-off."""
    diagnostic_findings = [
        finding
        for finding in findings
        if isinstance(finding, dict)
        and not str(finding.get("finding_id", "")).startswith("REF_")
        and str(finding.get("severity") or "diagnostic").strip().lower() != "info"
        and (_as_float(finding.get("confidence")) or 0) >= ORDER_MIN_CONFIDENCE
    ]
    if not diagnostic_findings:
        return []

    grouped = group_findings_by_source(diagnostic_findings)
    best_score_pct = grouped[0][0] * 100.0
    threshold_pct = best_score_pct - drop_off_points

    selected: list[Finding] = []
    for score, representative in grouped:
        if (score * 100.0) >= threshold_pct or not selected:
            selected.append(representative)
        if len(selected) >= max_causes:
            break

    result: list[TopCause] = []
    for representative in selected:
        label_key, tone, pct_text = confidence_label(
            _as_float(representative.get("confidence")) or 0,
            strength_band_key=strength_band_key,
        )
        result.append(
            {
                "finding_id": str(representative.get("finding_id") or ""),
                "source": str(representative.get("suspected_source") or ""),
                "confidence": representative.get("confidence"),
                "confidence_label_key": label_key,
                "confidence_tone": tone,
                "confidence_pct": pct_text,
                "order": str(representative.get("frequency_hz_or_order") or ""),
                "signatures_observed": representative.get("signatures_observed", []),
                "grouped_count": representative.get("grouped_count", 1),
                "strongest_location": representative.get("strongest_location"),
                "dominance_ratio": representative.get("dominance_ratio"),
                "strongest_speed_band": representative.get("strongest_speed_band"),
                "weak_spatial_separation": bool(representative.get("weak_spatial_separation")),
                "diffuse_excitation": representative.get("diffuse_excitation", False),
                "diagnostic_caveat": representative.get("diagnostic_caveat"),
                "phase_evidence": representative.get("phase_evidence"),
            },
        )
    return result
