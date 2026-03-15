"""Diagnostic test plan and next-step ownership."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.domain.diagnostics.recommended_action import RecommendedAction

__all__ = ["TestPlan"]


@dataclass(frozen=True, slots=True)
class TestPlan:
    """The intended diagnostic approach and next recommended actions."""

    actions: tuple[RecommendedAction, ...] = ()
    requires_additional_data: bool = False

    @property
    def has_actions(self) -> bool:
        return bool(self.actions)

    @property
    def supports_case_completion(self) -> bool:
        return not self.requires_additional_data

    @property
    def prioritized_actions(self) -> tuple[RecommendedAction, ...]:
        return tuple(sorted(self.actions, key=RecommendedAction.sort_key))

    @property
    def is_complete(self) -> bool:
        return self.supports_case_completion and not self.has_actions

    def needs_more_data(self) -> bool:
        return not self.supports_case_completion
