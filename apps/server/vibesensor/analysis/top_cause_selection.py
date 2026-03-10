"""Top-cause selection and lightweight confidence presentation helpers."""

from __future__ import annotations

import math

from ..constants import ORDER_MIN_CONFIDENCE
from ..domain_models import as_float_or_none as _as_float
from ._types import Finding, TopCause
from .ranking import group_findings_by_source
from .strength_labels import (
    CONFIDENCE_HIGH_THRESHOLD,
    CONFIDENCE_MEDIUM_THRESHOLD,
)


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
        and (_as_float(finding.get("confidence_0_to_1")) or 0) >= ORDER_MIN_CONFIDENCE
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
            _as_float(representative.get("confidence_0_to_1")) or 0,
            strength_band_key=strength_band_key,
        )
        result.append(
            {
                "finding_id": str(representative.get("finding_id") or ""),
                "source": str(representative.get("suspected_source") or ""),
                "confidence": representative.get("confidence_0_to_1"),
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
