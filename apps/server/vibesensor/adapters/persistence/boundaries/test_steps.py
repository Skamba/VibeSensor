"""Boundary projectors for persisted TestPlan and TestStep payloads."""

from __future__ import annotations

from vibesensor.domain.diagnostics.recommended_action import RecommendedAction
from vibesensor.domain.diagnostics.test_plan import TestPlan

__all__ = ["step_payload_from_action", "step_payloads_from_plan"]


def step_payload_from_action(action: RecommendedAction) -> dict[str, object]:
    """Project one semantic action into the persisted TestStep shape."""
    return {
        "action_id": action.action_id,
        "what": action.instruction,
        "why": action.rationale,
        "confirm": action.confirmation_signal,
        "falsify": action.falsification_signal,
        "eta": action.estimated_duration,
    }


def step_payloads_from_plan(test_plan: TestPlan) -> list[dict[str, object]]:
    """Project a semantic TestPlan into the persisted TestStep payload list."""
    return [step_payload_from_action(action) for action in test_plan.prioritized_actions]
