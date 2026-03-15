"""Hypothesis evaluation service."""

from __future__ import annotations

from collections.abc import Sequence

from vibesensor.domain.hypothesis import Hypothesis, HypothesisStatus
from vibesensor.domain.signature import Signature


def evaluate_hypotheses(signatures: Sequence[Signature]) -> tuple[Hypothesis, ...]:
    hypotheses: list[Hypothesis] = []
    for signature in signatures:
        status = (
            HypothesisStatus.SUPPORTED
            if signature.support_score >= Hypothesis.SUPPORTED_THRESHOLD
            else HypothesisStatus.INCONCLUSIVE
        )
        hypotheses.append(
            Hypothesis(
                hypothesis_id=f"hyp-{signature.key}",
                source=signature.source,
                signature_keys=(signature.key,),
                support_score=signature.support_score,
                contradiction_score=0.0,
                status=status,
                rationale=(f"Supported by {signature.label}",),
            )
        )
    return tuple(hypotheses)
