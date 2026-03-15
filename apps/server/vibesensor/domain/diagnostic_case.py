"""Case-level aggregate for one diagnostic problem over one investigation episode."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from uuid import uuid4

from .car import Car
from .configuration_snapshot import ConfigurationSnapshot
from .finding import Finding
from .hypothesis import Hypothesis, HypothesisStatus
from .recommended_action import RecommendedAction
from .symptom import Symptom
from .test_plan import TestPlan
from .test_run import TestRun

__all__ = ["DiagnosticCase", "DiagnosticCaseEpistemicRule"]


class DiagnosticCaseEpistemicRule(StrEnum):
    """Cross-run epistemic disposition for one candidate conclusion.

    These rules define the intended DiagnosticCase.reconcile contract ahead of
    the later full rewrite:

    - strengthening: later evidence increases support for the same conclusion.
    - weakening: later evidence still leans the same way, but with less support.
    - contradiction: runs provide materially conflicting evidence.
    - retirement: a later run explicitly retires the candidate.
    - unresolved_support: runs lean toward the candidate without resolving it.
    """

    STRENGTHENING = "strengthening"
    WEAKENING = "weakening"
    CONTRADICTION = "contradiction"
    RETIREMENT = "retirement"
    UNRESOLVED_SUPPORT = "unresolved_support"


@dataclass(frozen=True, slots=True)
class DiagnosticCase:
    """Top-level aggregate for the diagnostic problem under investigation."""

    case_id: str
    car: Car | None = None
    symptoms: tuple[Symptom, ...] = ()
    configuration_snapshots: tuple[ConfigurationSnapshot, ...] = ()
    test_plan: TestPlan = TestPlan()
    test_runs: tuple[TestRun, ...] = ()
    hypotheses: tuple[Hypothesis, ...] = ()
    findings: tuple[Finding, ...] = ()
    recommended_actions: tuple[RecommendedAction, ...] = ()

    _EMPTY_TEST_PLAN = TestPlan()

    @staticmethod
    def _hypothesis_net_support(hypothesis: Hypothesis) -> float:
        return hypothesis.support_score - hypothesis.contradiction_score

    @classmethod
    def classify_hypothesis_sequence(
        cls,
        hypotheses: tuple[Hypothesis, ...],
    ) -> DiagnosticCaseEpistemicRule:
        """Classify how one hypothesis evolves across multiple runs.

        The input tuple is expected to be in run order.
        """
        if not hypotheses:
            raise ValueError("DiagnosticCase.classify_hypothesis_sequence requires evidence")

        latest = hypotheses[-1]
        prior = hypotheses[:-1]
        if latest.status is HypothesisStatus.RETIRED:
            return DiagnosticCaseEpistemicRule.RETIREMENT

        prior_supported_scores = tuple(
            cls._hypothesis_net_support(hypothesis)
            for hypothesis in prior
            if hypothesis.ready_for_finding
        )
        has_supported_run = bool(prior_supported_scores) or latest.ready_for_finding
        has_contradictory_run = any(
            hypothesis.status in {HypothesisStatus.CONTRADICTED, HypothesisStatus.REJECTED}
            for hypothesis in hypotheses
        )
        if has_supported_run and has_contradictory_run:
            return DiagnosticCaseEpistemicRule.CONTRADICTION

        latest_net_support = cls._hypothesis_net_support(latest)
        strongest_prior_support = max(prior_supported_scores, default=0.0)
        if latest.ready_for_finding:
            if strongest_prior_support > 0.0 and latest_net_support > strongest_prior_support:
                return DiagnosticCaseEpistemicRule.STRENGTHENING
            if strongest_prior_support > 0.0 and latest_net_support < strongest_prior_support:
                return DiagnosticCaseEpistemicRule.WEAKENING
            if prior and latest_net_support > 0.0:
                return DiagnosticCaseEpistemicRule.STRENGTHENING

        if latest_net_support > 0.0 or latest.signature_keys:
            return DiagnosticCaseEpistemicRule.UNRESOLVED_SUPPORT
        return DiagnosticCaseEpistemicRule.WEAKENING

    @staticmethod
    def _finding_identity(finding: Finding) -> tuple[str, str | None]:
        location = finding.strongest_location
        if Finding.is_unknown_location(location):
            location = None
        return (finding.source_normalized, location)

    @classmethod
    def classify_finding_sequence(
        cls,
        findings: tuple[Finding, ...],
    ) -> DiagnosticCaseEpistemicRule:
        """Classify how one finding trajectory behaves across runs.

        The input tuple is expected to be in run order.
        """
        if not findings:
            raise ValueError("DiagnosticCase.classify_finding_sequence requires evidence")

        latest = findings[-1]
        actionable_findings = tuple(finding for finding in findings if finding.is_actionable)
        actionable_keys = {cls._finding_identity(finding) for finding in actionable_findings}
        if len(actionable_keys) > 1:
            return DiagnosticCaseEpistemicRule.CONTRADICTION
        if not latest.is_actionable:
            return DiagnosticCaseEpistemicRule.UNRESOLVED_SUPPORT

        latest_key = cls._finding_identity(latest)
        prior_scores = tuple(
            finding.phase_adjusted_score
            for finding in findings[:-1]
            if finding.is_actionable and cls._finding_identity(finding) == latest_key
        )
        if not prior_scores:
            return DiagnosticCaseEpistemicRule.UNRESOLVED_SUPPORT

        strongest_prior_score = max(prior_scores)
        if latest.phase_adjusted_score > strongest_prior_score:
            return DiagnosticCaseEpistemicRule.STRENGTHENING
        if latest.phase_adjusted_score < strongest_prior_score:
            return DiagnosticCaseEpistemicRule.WEAKENING
        return DiagnosticCaseEpistemicRule.UNRESOLVED_SUPPORT

    def hypothesis_epistemic_rules(self) -> dict[str, DiagnosticCaseEpistemicRule]:
        """Return the explicit cross-run rule outcome for each hypothesis id."""
        grouped: dict[str, list[Hypothesis]] = {}
        for test_run in self.test_runs:
            for hypothesis in test_run.hypotheses:
                grouped.setdefault(hypothesis.hypothesis_id, []).append(hypothesis)
        return {
            hypothesis_id: self.classify_hypothesis_sequence(tuple(sequence))
            for hypothesis_id, sequence in grouped.items()
        }

    @classmethod
    def start(
        cls,
        *,
        car: Car | None = None,
        symptoms: tuple[Symptom, ...] = (),
        configuration_snapshots: tuple[ConfigurationSnapshot, ...] = (),
        test_plan: TestPlan | None = None,
    ) -> DiagnosticCase:
        return cls(
            case_id=uuid4().hex,
            car=car,
            symptoms=symptoms or (Symptom.unspecified(),),
            configuration_snapshots=configuration_snapshots,
            test_plan=test_plan or cls._EMPTY_TEST_PLAN,
        )

    def add_run(self, test_run: TestRun) -> DiagnosticCase:
        snapshots = self.configuration_snapshots
        if test_run.configuration_snapshot not in snapshots:
            snapshots = (*snapshots, test_run.configuration_snapshot)
        updated = replace(
            self,
            test_runs=(*self.test_runs, test_run),
            configuration_snapshots=snapshots,
        )
        return updated.reconcile()

    def reconcile(self) -> DiagnosticCase:
        """Produce case-level conclusions from the contributing runs.

        Uses ``classify_hypothesis_sequence()`` and
        ``classify_finding_sequence()`` to apply epistemic rules across runs.
        Retired hypotheses are excluded. Latest-run evidence is preferred over
        best-ever-score for both hypotheses and findings.
        """
        # ── Hypotheses: group by id, classify, keep latest (exclude retired) ──
        hyp_sequences: dict[str, list[Hypothesis]] = {}
        for test_run in self.test_runs:
            for hypothesis in test_run.hypotheses:
                hyp_sequences.setdefault(hypothesis.hypothesis_id, []).append(hypothesis)

        kept_hypotheses: dict[str, Hypothesis] = {}
        for hyp_id, sequence in hyp_sequences.items():
            rule = self.classify_hypothesis_sequence(tuple(sequence))
            if rule is DiagnosticCaseEpistemicRule.RETIREMENT:
                continue
            kept_hypotheses[hyp_id] = sequence[-1]

        # ── Findings: group by _finding_identity, keep latest ──
        finding_sequences: dict[tuple[str, str | None], list[Finding]] = {}
        for test_run in self.test_runs:
            for finding in test_run.effective_top_causes():
                key = self._finding_identity(finding)
                finding_sequences.setdefault(key, []).append(finding)

        kept_findings: dict[tuple[str, str | None], Finding] = {}
        for key, finding_seq in finding_sequences.items():
            kept_findings[key] = finding_seq[-1]

        # ── Actions: lowest priority wins (unchanged) ──
        actions: dict[str, RecommendedAction] = {
            action.action_id: action for action in self.test_plan.prioritized_actions
        }
        for test_run in self.test_runs:
            for action in test_run.recommended_actions:
                if (
                    action.action_id not in actions
                    or action.priority < actions[action.action_id].priority
                ):
                    actions[action.action_id] = action

        return replace(
            self,
            hypotheses=tuple(
                sorted(
                    kept_hypotheses.values(),
                    key=lambda item: (-item.support_score, item.hypothesis_id),
                )
            ),
            findings=tuple(
                sorted(kept_findings.values(), key=lambda item: item.rank_key, reverse=True)
            ),
            recommended_actions=tuple(sorted(actions.values(), key=RecommendedAction.sort_key)),
        )

    @property
    def primary_run(self) -> TestRun | None:
        return self.test_runs[-1] if self.test_runs else None

    @property
    def has_usable_evidence(self) -> bool:
        """Whether the case has genuinely usable diagnostic evidence."""
        if not any(f.is_actionable for f in self.findings):
            return False
        primary = self.primary_run
        if primary is not None and primary.suitability is not None:
            if not primary.suitability.is_usable:
                return False
        return True

    @property
    def is_complete(self) -> bool:
        return self.has_usable_evidence and self.test_plan.supports_case_completion

    @property
    def evidence_gaps(self) -> tuple[str, ...]:
        """Descriptions of what evidence is missing or weak."""
        gaps: list[str] = []
        if not self.findings:
            gaps.append("no_findings")
        elif not any(f.is_actionable for f in self.findings):
            gaps.append("no_actionable_findings")
        primary = self.primary_run
        if primary is not None and primary.suitability is not None:
            if not primary.suitability.is_usable:
                gaps.append("primary_run_unusable")
        if self.test_plan.requires_additional_data:
            gaps.append("additional_data_required")
        return tuple(gaps)

    @property
    def needs_more_data(self) -> bool:
        return not self.is_complete
