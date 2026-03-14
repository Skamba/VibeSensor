"""Diagnostic test plan and next-step ownership."""

from __future__ import annotations

from dataclasses import dataclass

from .recommended_action import RecommendedAction

__all__ = ["TestPlan"]


@dataclass(frozen=True, slots=True)
class TestPlan:
    """The intended diagnostic approach and next recommended actions."""

    actions: tuple[RecommendedAction, ...] = ()
    requires_additional_data: bool = False

    @property
    def prioritized_actions(self) -> tuple[RecommendedAction, ...]:
        return tuple(sorted(self.actions, key=RecommendedAction.sort_key))

    @property
    def is_complete(self) -> bool:
        return not self.requires_additional_data and not self.actions

    def needs_more_data(self) -> bool:
        return self.requires_additional_data or not self.actions
