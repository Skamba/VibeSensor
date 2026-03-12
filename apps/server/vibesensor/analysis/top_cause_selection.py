"""Top-cause selection, ranking helpers, and confidence presentation.

Ranking helpers (``finding_sort_key``, ``phase_adjusted_ranking_score``,
``group_findings_by_source``) were previously in a separate ``ranking``
module but merged here because this module is their primary consumer and
no other production module needs them independently.

``OrderAssessment`` is a rich internal object that represents the
interpreted result of evaluating one order candidate.  It owns
actionability, severity/certainty banding, ranking/comparison, and
surfacing decisions that were previously re-derived in multiple places.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from ..constants import ORDER_MIN_CONFIDENCE
from ..domain_models import as_float_or_none as _as_float
from ._types import Finding, JsonValue, PhaseEvidence, TopCause
from .diagnosis_candidates import _PLACEHOLDER_SOURCES, is_actionable_location
from .strength_labels import (
    CONFIDENCE_HIGH_THRESHOLD,
    CONFIDENCE_MEDIUM_THRESHOLD,
)

# ---------------------------------------------------------------------------
# OrderAssessment
# ---------------------------------------------------------------------------

_QUANTISE_STEP = 0.02
_QUANTISE_INV = 1.0 / _QUANTISE_STEP


@dataclass(frozen=True)
class OrderAssessment:
    """Interpreted assessment of a single order-tracking candidate.

    Owns actionability, severity/certainty banding, ranking/comparison
    helpers, and surfacing decisions so that callers no longer need to
    re-derive these from raw dict fields.
    """

    finding_id: str
    source: str
    confidence: float | None
    ranking_score: float
    severity: str
    strongest_location: str | None
    strongest_speed_band: str | None
    phase_evidence: PhaseEvidence | None
    diffuse_excitation: bool
    weak_spatial_separation: bool
    dominance_ratio: float | None
    signatures_observed: list[str]
    grouped_count: int
    diagnostic_caveat: JsonValue
    order: str

    # -- construction -------------------------------------------------------

    @staticmethod
    def from_finding(finding: Finding) -> OrderAssessment:
        """Build an assessment from a Finding dict."""
        return OrderAssessment(
            finding_id=str(finding.get("finding_id") or ""),
            source=str(finding.get("suspected_source") or ""),
            confidence=_as_float(finding.get("confidence")),
            ranking_score=_as_float(finding.get("_ranking_score")) or 0.0,
            severity=str(finding.get("severity") or "diagnostic").strip().lower(),
            strongest_location=finding.get("strongest_location"),
            strongest_speed_band=finding.get("strongest_speed_band"),
            phase_evidence=finding.get("phase_evidence"),
            diffuse_excitation=finding.get("diffuse_excitation", False),
            weak_spatial_separation=bool(finding.get("weak_spatial_separation")),
            dominance_ratio=finding.get("dominance_ratio"),
            signatures_observed=finding.get("signatures_observed", []),
            grouped_count=finding.get("grouped_count", 1),
            diagnostic_caveat=finding.get("diagnostic_caveat"),
            order=str(finding.get("frequency_hz_or_order") or ""),
        )

    # -- effective confidence -----------------------------------------------

    @property
    def effective_confidence(self) -> float:
        """Confidence normalised for computation (``None`` → ``0.0``)."""
        return float(self.confidence) if self.confidence is not None else 0.0

    # -- actionability / surfacing ------------------------------------------

    @property
    def is_reference(self) -> bool:
        """Whether this is a reference-data finding (``REF_*``)."""
        return self.finding_id.strip().upper().startswith("REF_")

    @property
    def is_actionable(self) -> bool:
        """Whether this candidate is actionable enough for report rendering."""
        source_lower = self.source.strip().lower()
        return source_lower not in _PLACEHOLDER_SOURCES or is_actionable_location(
            self.strongest_location,
        )

    @property
    def should_surface(self) -> bool:
        """Whether this finding should appear in report output.

        Filters out reference findings, informational findings, and those
        below the minimum confidence floor.
        """
        if self.is_reference:
            return False
        if self.severity == "info":
            return False
        return self.effective_confidence >= ORDER_MIN_CONFIDENCE

    # -- severity / certainty banding ----------------------------------------

    def severity_band(self) -> str:
        """Return the severity classification (e.g. ``'diagnostic'``, ``'info'``)."""
        return self.severity

    def certainty_band(
        self,
        *,
        strength_band_key: str | None = None,
    ) -> tuple[str, str, str]:
        """Return ``(label_key, tone, pct_text)`` for this assessment."""
        return confidence_label(
            self.effective_confidence,
            strength_band_key=strength_band_key,
        )

    # -- ranking / comparison ------------------------------------------------

    @property
    def rank_key(self) -> tuple[float, float]:
        """Deterministic sort key for stable finding ordering."""
        quantised = round(self.effective_confidence * _QUANTISE_INV) * _QUANTISE_STEP
        return (quantised, self.ranking_score)

    @property
    def phase_adjusted_score(self) -> float:
        """Phase-aware ranking score used for top-cause selection."""
        cruise_fraction = (
            float(self.phase_evidence.get("cruise_fraction", 0.0))
            if isinstance(self.phase_evidence, dict)
            else 0.0
        )
        return self.effective_confidence * (0.85 + 0.15 * cruise_fraction)

    def is_stronger_than(self, other: OrderAssessment) -> bool:
        """Whether this assessment ranks higher than *other*."""
        return self.phase_adjusted_score > other.phase_adjusted_score

    # -- serialisation helpers -----------------------------------------------

    def to_top_cause(
        self,
        *,
        strength_band_key: str | None = None,
    ) -> TopCause:
        """Build a ``TopCause`` dict from this assessment."""
        label_key, tone, pct_text = self.certainty_band(
            strength_band_key=strength_band_key,
        )
        return {
            "finding_id": self.finding_id,
            "source": self.source,
            "confidence": self.confidence,
            "confidence_label_key": label_key,
            "confidence_tone": tone,
            "confidence_pct": pct_text,
            "order": self.order,
            "signatures_observed": self.signatures_observed,
            "grouped_count": self.grouped_count,
            "strongest_location": self.strongest_location,
            "dominance_ratio": self.dominance_ratio,
            "strongest_speed_band": self.strongest_speed_band,
            "weak_spatial_separation": self.weak_spatial_separation,
            "diffuse_excitation": self.diffuse_excitation,
            "diagnostic_caveat": self.diagnostic_caveat,
            "phase_evidence": self.phase_evidence,
        }


# ---------------------------------------------------------------------------
# Standalone ranking helpers (thin delegates to OrderAssessment)
# ---------------------------------------------------------------------------


def finding_sort_key(item: Finding) -> tuple[float, float]:
    """Return a deterministic sort key for findings.

    Confidence is quantised so tiny timing/noise jitter does not reshuffle
    otherwise equivalent findings, leaving the explicit ranking score to break
    ties consistently.
    """
    return OrderAssessment.from_finding(item).rank_key


def phase_adjusted_ranking_score(finding: Finding) -> float:
    """Compute the phase-aware score used for top-cause selection."""
    return OrderAssessment.from_finding(finding).phase_adjusted_score


def group_findings_by_source(diag_findings: list[Finding]) -> list[tuple[float, Finding]]:
    """Group findings by source and return ranked representatives."""
    groups: dict[str, list[Finding]] = defaultdict(list)
    for finding in diag_findings:
        source = str(finding.get("suspected_source") or "unknown").strip().lower()
        groups[source].append(finding)

    grouped: list[tuple[float, Finding]] = []
    for members in groups.values():
        members_scored = sorted(
            (
                (OrderAssessment.from_finding(member).phase_adjusted_score, member)
                for member in members
            ),
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
        if isinstance(finding, dict) and OrderAssessment.from_finding(finding).should_surface
    ]
    if not diagnostic_findings:
        return []

    grouped = group_findings_by_source(diagnostic_findings)
    best_score_pct = grouped[0][0] * 100.0
    threshold_pct = best_score_pct - drop_off_points

    selected: list[OrderAssessment] = []
    for score, representative in grouped:
        if (score * 100.0) >= threshold_pct or not selected:
            selected.append(OrderAssessment.from_finding(representative))
        if len(selected) >= max_causes:
            break

    return [assessment.to_top_cause(strength_band_key=strength_band_key) for assessment in selected]
