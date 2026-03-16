"""Run-scoped diagnostic reasoning model.

Co-locates the tightly coupled reasoning chain types—Observation, Signature,
Hypothesis, and DiagnosticReasoning—that are always constructed and consumed
together within the analysis pipeline.  The service functions that operate on
these types (extract_observations, recognize_signatures, evaluate_hypotheses)
live here alongside their data types.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar

from vibesensor.domain.driving_segment import DrivingPhase
from vibesensor.domain.finding import VibrationSource

if TYPE_CHECKING:
    from vibesensor.domain.finding import Finding

__all__ = [
    "DiagnosticReasoning",
    "Hypothesis",
    "HypothesisStatus",
    "Observation",
    "ObservationEvidence",
    "Signature",
    "evaluate_hypotheses",
    "extract_observations",
    "recognize_signatures",
]


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Observation:
    """One diagnostically meaningful observation."""

    observation_id: str
    kind: str
    source: VibrationSource
    signature_key: str
    magnitude_db: float | None = None
    speed_band: str | None = None
    phase: DrivingPhase | None = None
    location: str | None = None
    support_score: float = 0.0

    @property
    def supports_signature(self) -> bool:
        return bool(self.signature_key.strip()) and self.support_score > 0.0


@dataclass(frozen=True, slots=True)
class ObservationEvidence:
    """Pre-finding evidence needed for observation extraction."""

    source: VibrationSource
    signature_labels: tuple[str, ...]
    magnitude_db: float | None
    speed_band: str | None
    dominant_phase: str | None
    location: str | None
    confidence: float


# ---------------------------------------------------------------------------
# Signature
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Signature:
    """A meaningful vibration pattern with supporting observations."""

    key: str
    source: VibrationSource
    label: str
    observation_ids: tuple[str, ...] = ()
    support_score: float = 0.0

    @property
    def observation_count(self) -> int:
        return len(self.observation_ids)

    @property
    def is_consistent(self) -> bool:
        return len(self.observation_ids) > 0 and self.support_score > 0.0

    @classmethod
    def from_label(
        cls,
        label: str,
        *,
        source: VibrationSource,
        observation_ids: tuple[str, ...] = (),
        support_score: float = 0.0,
    ) -> Signature:
        key = label.strip().lower().replace("/", "_").replace(" ", "_") or "unknown_signature"
        return cls(
            key=key,
            source=source,
            label=label.strip() or "unknown signature",
            observation_ids=observation_ids,
            support_score=support_score,
        )


# ---------------------------------------------------------------------------
# Hypothesis
# ---------------------------------------------------------------------------


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

    SUPPORTED_THRESHOLD: ClassVar[float] = 0.40

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

    @classmethod
    def from_finding(cls, finding: Finding, signatures: tuple[Signature, ...]) -> Hypothesis:
        """Build a hypothesis from a completed finding and its signatures."""
        status = (
            HypothesisStatus.SUPPORTED
            if finding.effective_confidence >= cls.SUPPORTED_THRESHOLD
            else HypothesisStatus.INCONCLUSIVE
        )
        return cls(
            hypothesis_id=finding.finding_id or f"hyp-{finding.suspected_source}",
            source=finding.suspected_source,
            signature_keys=tuple(sig.key for sig in signatures),
            support_score=finding.effective_confidence,
            contradiction_score=0.0,
            status=status,
            rationale=(
                (finding.confidence_assessment.reason,)
                if finding.confidence_assessment and finding.confidence_assessment.reason
                else ()
            ),
        )


# ---------------------------------------------------------------------------
# DiagnosticReasoning (aggregate)
# ---------------------------------------------------------------------------


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

    @classmethod
    def from_findings(cls, findings: Sequence[Finding]) -> DiagnosticReasoning:
        """Build reasoning from run-level findings.

        Reference findings are excluded from hypothesis generation.
        Observations are not populated (known inversion: findings are built
        first, reasoning is retroactively derived).
        """
        signatures: list[Signature] = []
        hypotheses: list[Hypothesis] = []
        for f in findings:
            if f.is_reference:
                continue
            signatures.extend(f.signatures)
            hypotheses.append(Hypothesis.from_finding(f, f.signatures))
        return cls(
            observations=(),
            signatures=tuple(dict.fromkeys(signatures)),
            hypotheses=tuple(hypotheses),
        )


# ---------------------------------------------------------------------------
# Reasoning-chain service functions
# ---------------------------------------------------------------------------


def extract_observations(evidence: Sequence[ObservationEvidence]) -> tuple[Observation, ...]:
    """Derive diagnostically meaningful observations from pre-finding evidence."""
    observations: list[Observation] = []
    for ev_idx, ev in enumerate(evidence, start=1):
        dominant_phase = (ev.dominant_phase or "").upper()
        phase = DrivingPhase[dominant_phase] if dominant_phase in DrivingPhase.__members__ else None
        for sig_idx, label in enumerate(ev.signature_labels, start=1):
            if not label.strip():
                continue
            observations.append(
                Observation(
                    observation_id=f"obs-{ev_idx}-{sig_idx}",
                    kind="signature-support",
                    source=ev.source,
                    signature_key=label.strip().lower().replace(" ", "_"),
                    magnitude_db=ev.magnitude_db,
                    speed_band=ev.speed_band,
                    phase=phase,
                    location=ev.location,
                    support_score=ev.confidence,
                )
            )
    return tuple(observations)


def recognize_signatures(observations: Sequence[Observation]) -> tuple[Signature, ...]:
    """Group observations into signatures by source and signature key."""
    grouped: dict[tuple[str, str], list[Observation]] = defaultdict(list)
    for obs in observations:
        if not obs.supports_signature:
            continue
        grouped[(str(obs.source), obs.signature_key)].append(obs)
    signatures: list[Signature] = []
    for (_source_raw, signature_key), grouped_obs in grouped.items():
        signatures.append(
            Signature(
                key=signature_key,
                source=grouped_obs[0].source,
                label=grouped_obs[0].signature_key.replace("_", " "),
                observation_ids=tuple(o.observation_id for o in grouped_obs),
                support_score=min(1.0, sum(o.support_score for o in grouped_obs)),
            )
        )
    return tuple(sorted(signatures, key=lambda s: (-s.support_score, s.key)))


def evaluate_hypotheses(signatures: Sequence[Signature]) -> tuple[Hypothesis, ...]:
    """Evaluate signatures into hypotheses with support status."""
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
