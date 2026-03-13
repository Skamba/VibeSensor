"""Top-cause selection, ranking helpers, and confidence presentation.

Ranking helper ``group_findings_by_source`` was previously in a separate
``ranking`` module but merged here because this module is its primary
consumer and no other production module needs it independently.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import replace as _replace

from ..domain import Finding
from ._types import FindingPayload, TopCause
from .strength_labels import (
    CONFIDENCE_HIGH_THRESHOLD,
    CONFIDENCE_MEDIUM_THRESHOLD,
    _is_negligible_band,
)

# ---------------------------------------------------------------------------
# Top-cause building
# ---------------------------------------------------------------------------


def _build_top_cause(
    finding: FindingPayload,
    *,
    strength_band_key: str | None = None,
) -> TopCause:
    """Build a ``TopCause`` dict from a (grouped) FindingPayload."""
    domain = Finding.from_payload(finding)
    # Apply severity default and extract analysis-specific order key
    severity_raw = str(finding.get("severity") or "diagnostic").strip().lower()
    order_raw = str(finding.get("frequency_hz_or_order") or finding.get("order") or "")
    domain = _replace(domain, severity=severity_raw, order=order_raw)

    label_key, tone, pct_text = confidence_label(
        domain.effective_confidence,
        strength_band_key=strength_band_key,
    )
    return {
        "finding_id": domain.finding_id,
        "suspected_source": domain.suspected_source,
        "confidence": domain.confidence,
        "confidence_label_key": label_key,
        "confidence_tone": tone,
        "confidence_pct": pct_text,
        "order": domain.order,
        "signatures_observed": finding.get("signatures_observed", []),
        "grouped_count": finding.get("grouped_count", 1),
        "strongest_location": domain.strongest_location,
        "dominance_ratio": domain.dominance_ratio,
        "strongest_speed_band": domain.strongest_speed_band,
        "weak_spatial_separation": domain.weak_spatial_separation,
        "diffuse_excitation": domain.diffuse_excitation,
        "diagnostic_caveat": finding.get("diagnostic_caveat"),
        "phase_evidence": (
            {"cruise_fraction": domain.cruise_fraction} if domain.cruise_fraction else None
        ),
    }


# ---------------------------------------------------------------------------
# Source grouping
# ---------------------------------------------------------------------------


def group_findings_by_source(
    diag_findings: list[FindingPayload],
) -> list[tuple[float, FindingPayload]]:
    """Group findings by source and return ranked representatives."""
    groups: dict[str, list[FindingPayload]] = defaultdict(list)
    for finding in diag_findings:
        source = str(finding.get("suspected_source") or "unknown").strip().lower()
        groups[source].append(finding)

    grouped: list[tuple[float, FindingPayload]] = []
    for members in groups.values():
        members_scored = sorted(
            ((Finding.from_payload(member).phase_adjusted_score, member) for member in members),
            key=lambda item: item[0],
            reverse=True,
        )
        representative: FindingPayload = {**members_scored[0][1]}
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
    if _is_negligible_band(strength_band_key) and label_key == "CONFIDENCE_HIGH":
        label_key, tone = "CONFIDENCE_MEDIUM", "warn"
    return label_key, tone, pct_text


def select_top_causes(
    findings: list[FindingPayload],
    *,
    drop_off_points: float = 15.0,
    max_causes: int = 3,
    strength_band_key: str | None = None,
) -> list[TopCause]:
    """Group findings by source, rank the strongest group per source, and trim by drop-off."""
    diagnostic_findings = [
        finding
        for finding in findings
        if isinstance(finding, dict) and Finding.from_payload(finding).should_surface
    ]
    if not diagnostic_findings:
        return []

    grouped = group_findings_by_source(diagnostic_findings)
    best_score_pct = grouped[0][0] * 100.0
    threshold_pct = best_score_pct - drop_off_points

    selected: list[FindingPayload] = []
    for score, representative in grouped:
        if (score * 100.0) >= threshold_pct or not selected:
            selected.append(representative)
        if len(selected) >= max_causes:
            break

    return [_build_top_cause(f, strength_band_key=strength_band_key) for f in selected]
