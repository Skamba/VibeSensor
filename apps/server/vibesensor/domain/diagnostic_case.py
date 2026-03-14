"""Case-level aggregate for one diagnostic problem over one investigation episode."""

from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import uuid4

from .car import Car
from .configuration_snapshot import ConfigurationSnapshot
from .finding import Finding
from .hypothesis import Hypothesis
from .recommended_action import RecommendedAction
from .symptom import Symptom
from .test_plan import TestPlan
from .test_run import TestRun

__all__ = ["DiagnosticCase"]


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
        """Produce case-level conclusions from the contributing runs."""
        hypotheses: dict[str, Hypothesis] = {}
        findings: dict[tuple[str, str | None], Finding] = {}
        actions: dict[str, RecommendedAction] = {
            action.action_id: action for action in self.test_plan.prioritized_actions
        }
        for test_run in self.test_runs:
            for hypothesis in test_run.hypotheses:
                existing = hypotheses.get(hypothesis.hypothesis_id)
                if existing is None or hypothesis.support_score > existing.support_score:
                    hypotheses[hypothesis.hypothesis_id] = hypothesis
            for finding in test_run.effective_top_causes():
                key = (str(finding.suspected_source), finding.strongest_location)
                existing_finding = findings.get(key)
                if (
                    existing_finding is None
                    or finding.phase_adjusted_score > existing_finding.phase_adjusted_score
                ):
                    findings[key] = finding
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
                    hypotheses.values(),
                    key=lambda item: (-item.support_score, item.hypothesis_id),
                )
            ),
            findings=tuple(sorted(findings.values(), key=lambda item: item.rank_key, reverse=True)),
            recommended_actions=tuple(sorted(actions.values(), key=RecommendedAction.sort_key)),
        )

    @property
    def primary_run(self) -> TestRun | None:
        return self.test_runs[-1] if self.test_runs else None

    @property
    def is_complete(self) -> bool:
        return bool(self.findings) and self.test_plan.supports_case_completion

    @property
    def needs_more_data(self) -> bool:
        return not self.is_complete
