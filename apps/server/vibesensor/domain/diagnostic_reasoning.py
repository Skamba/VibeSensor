"""Run-scoped reasoning model inside a TestRun."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.domain.hypothesis import Hypothesis, HypothesisStatus
from vibesensor.domain.observation import Observation
from vibesensor.domain.signature import Signature

__all__ = ["DiagnosticReasoning"]


@dataclass(frozen=True, slots=True)
class DiagnosticReasoning:
    """Run-scoped reasoning derived from captured evidence.

    Groups the intermediate diagnostic concepts (Observation, Signature,
    Hypothesis) that support the derivation of Finding within a TestRun.
    """

    observations: tuple[Observation, ...] = ()
    signatures: tuple[Signature, ...] = ()
    hypotheses: tuple[Hypothesis, ...] = ()

    @property
    def has_unresolved_hypotheses(self) -> bool:
        """True if any hypothesis has a non-terminal status."""
        _terminal = {
            HypothesisStatus.SUPPORTED,
            HypothesisStatus.RETIRED,
            HypothesisStatus.CONTRADICTED,
            HypothesisStatus.REJECTED,
        }
        return any(h.status not in _terminal for h in self.hypotheses)

    @property
    def primary_signature(self) -> Signature | None:
        """First signature by construction order, or None."""
        return self.signatures[0] if self.signatures else None
