"""Recommended diagnostic or repair follow-up action."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["RecommendedAction"]


@dataclass(frozen=True, slots=True)
class RecommendedAction:
    """A concrete next step derived from findings or unresolved hypotheses."""

    action_id: str
    what: str
    why: str = ""
    confirm: str = ""
    falsify: str = ""
    eta: str | None = None
    priority: int = 100

    def sort_key(self) -> tuple[int, str]:
        return (self.priority, self.action_id)
