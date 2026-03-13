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

from ..domain.core import Finding
from ._types import FindingPayload, JsonValue, TopCause
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

    Core classification and ranking logic is delegated to the domain
    :class:`~vibesensor.domain.core.Finding` object held in
    :attr:`domain_finding`.  Report-level aggregation fields
    (``signatures_observed``, ``grouped_count``, ``diagnostic_caveat``)
    remain on this class because they are grouping artifacts created
    during top-cause selection, not intrinsic finding properties.
    """

    # Domain finding (carries classification, ranking, actionability)
    domain_finding: Finding

    # Report-level aggregation fields (not intrinsic to a finding)
    signatures_observed: list[str]
    grouped_count: int
    diagnostic_caveat: JsonValue

    # -- delegated properties -----------------------------------------------

    @property
    def finding_id(self) -> str:
        return self.domain_finding.finding_id

    @property
    def source(self) -> str:
        return self.domain_finding.suspected_source

    @property
    def confidence(self) -> float | None:
        return self.domain_finding.confidence

    @property
    def ranking_score(self) -> float:
        return self.domain_finding.ranking_score

    @property
    def severity(self) -> str:
        return self.domain_finding.severity

    @property
    def strongest_location(self) -> str | None:
        return self.domain_finding.strongest_location

    @property
    def strongest_speed_band(self) -> str | None:
        return self.domain_finding.strongest_speed_band

    @property
    def phase_evidence(self) -> dict[str, float] | None:
        return self.domain_finding.phase_evidence

    @property
    def diffuse_excitation(self) -> bool:
        return self.domain_finding.diffuse_excitation

    @property
    def weak_spatial_separation(self) -> bool:
        return self.domain_finding.weak_spatial_separation

    @property
    def dominance_ratio(self) -> float | None:
        return self.domain_finding.dominance_ratio

    @property
    def order(self) -> str:
        return self.domain_finding.order

    # -- construction -------------------------------------------------------

    @staticmethod
    def from_finding(finding: FindingPayload) -> OrderAssessment:
        """Build an assessment from a FindingPayload dict."""
        from dataclasses import replace as _replace

        domain = Finding.from_payload(finding)
        # Apply severity default and extract analysis-specific order key
        severity_raw = str(finding.get("severity") or "diagnostic").strip().lower()
        order_raw = str(finding.get("frequency_hz_or_order") or finding.get("order") or "")
        domain = _replace(domain, severity=severity_raw, order=order_raw)
        return OrderAssessment(
            domain_finding=domain,
            signatures_observed=finding.get("signatures_observed", []),
            grouped_count=finding.get("grouped_count", 1),
            diagnostic_caveat=finding.get("diagnostic_caveat"),
        )

    # -- delegated classification -------------------------------------------

    @property
    def effective_confidence(self) -> float:
        """Confidence normalised for computation (``None`` → ``0.0``)."""
        return self.domain_finding.effective_confidence

    @property
    def is_reference(self) -> bool:
        """Whether this is a reference-data finding (``REF_*``)."""
        return self.domain_finding.is_reference

    @property
    def is_actionable(self) -> bool:
        """Whether this candidate is actionable enough for report rendering."""
        return self.domain_finding.is_actionable

    @property
    def should_surface(self) -> bool:
        """Whether this finding should appear in report output."""
        return self.domain_finding.should_surface

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
        return self.domain_finding.rank_key

    @property
    def phase_adjusted_score(self) -> float:
        """Phase-aware ranking score used for top-cause selection."""
        return self.domain_finding.phase_adjusted_score

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
            "phase_evidence": self.phase_evidence,  # type: ignore[typeddict-item]
        }


# ---------------------------------------------------------------------------
# Standalone ranking helpers (thin delegates to OrderAssessment)
# ---------------------------------------------------------------------------


def finding_sort_key(item: FindingPayload) -> tuple[float, float]:
    """Return a deterministic sort key for findings.

    Confidence is quantised so tiny timing/noise jitter does not reshuffle
    otherwise equivalent findings, leaving the explicit ranking score to break
    ties consistently.
    """
    return OrderAssessment.from_finding(item).rank_key


def phase_adjusted_ranking_score(finding: FindingPayload) -> float:
    """Compute the phase-aware score used for top-cause selection."""
    return OrderAssessment.from_finding(finding).phase_adjusted_score


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
            (
                (OrderAssessment.from_finding(member).phase_adjusted_score, member)
                for member in members
            ),
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
    if (strength_band_key or "").strip().lower() == "negligible" and label_key == "CONFIDENCE_HIGH":
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
