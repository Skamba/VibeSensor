"""Possible explanation for the complaint under investigation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from .finding import VibrationSource

__all__ = ["Hypothesis", "HypothesisStatus"]


class HypothesisStatus(StrEnum):
    CANDIDATE = "candidate"
    SUPPORTED = "supported"
    INCONCLUSIVE = "inconclusive"
    CONTRADICTED = "contradicted"
    REJECTED = "rejected"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class Hypothesis:
    """A candidate explanation with support/contradiction state."""

    hypothesis_id: str
    source: VibrationSource
    signature_keys: tuple[str, ...] = ()
    support_score: float = 0.0
    contradiction_score: float = 0.0
    status: HypothesisStatus = HypothesisStatus.CANDIDATE
    rationale: tuple[str, ...] = ()

    @property
    def is_supported(self) -> bool:
        return self.status is HypothesisStatus.SUPPORTED

    @property
    def ready_for_finding(self) -> bool:
        return (
            self.status is HypothesisStatus.SUPPORTED
            and self.support_score > self.contradiction_score
        )

    def support_with(self, signature_key: str, score: float, reason: str = "") -> Hypothesis:
        signatures = self.signature_keys
        if signature_key and signature_key not in signatures:
            signatures = (*signatures, signature_key)
        return replace(
            self,
            signature_keys=signatures,
            support_score=self.support_score + max(score, 0.0),
            status=HypothesisStatus.SUPPORTED,
            rationale=(*self.rationale, reason) if reason else self.rationale,
        )

    def contradict_with(self, score: float, reason: str = "") -> Hypothesis:
        status = HypothesisStatus.CONTRADICTED
        if self.contradiction_score + max(score, 0.0) > self.support_score:
            status = HypothesisStatus.REJECTED
        return replace(
            self,
            contradiction_score=self.contradiction_score + max(score, 0.0),
            status=status,
            rationale=(*self.rationale, reason) if reason else self.rationale,
        )

    def retire(self, reason: str = "") -> Hypothesis:
        return replace(
            self,
            status=HypothesisStatus.RETIRED,
            rationale=(*self.rationale, reason) if reason else self.rationale,
        )
