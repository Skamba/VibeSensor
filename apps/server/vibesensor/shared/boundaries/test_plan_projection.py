"""Project domain test-plan objects into persisted boundary payloads."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain.test_plan import RecommendedAction, TestPlan
from vibesensor.shared.boundaries.analysis_payload import TestPlanStepPayload

__all__ = [
    "step_payload_from_action",
    "step_payloads_from_plan",
]


def _has_structured_step_content(steps: object) -> bool:
    if not isinstance(steps, list):
        return False
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        for key in ("what", "why", "confirm", "falsify"):
            value = step.get(key)
            if isinstance(value, (Mapping, list)):
                return True
    return False


def step_payload_from_action(action: RecommendedAction) -> TestPlanStepPayload:
    """Project one semantic action into the persisted test-step shape."""
    return {
        "action_id": action.action_id,
        "what": action.instruction,
        "why": action.rationale,
        "confirm": action.confirmation_signal,
        "falsify": action.falsification_signal,
        "eta": action.estimated_duration,
    }


def step_payloads_from_plan(test_plan: TestPlan) -> list[TestPlanStepPayload]:
    """Project a semantic TestPlan into the persisted TestStep payload list."""
    return [step_payload_from_action(action) for action in test_plan.prioritized_actions]
