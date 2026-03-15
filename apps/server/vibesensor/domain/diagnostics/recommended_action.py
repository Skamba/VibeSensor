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

    @property
    def instruction(self) -> str:
        return self.what.strip()

    @property
    def rationale(self) -> str | None:
        value = self.why.strip()
        return value or None

    @property
    def confirmation_signal(self) -> str | None:
        value = self.confirm.strip()
        return value or None

    @property
    def falsification_signal(self) -> str | None:
        value = self.falsify.strip()
        return value or None

    @property
    def estimated_duration(self) -> str | None:
        if self.eta is None:
            return None
        value = self.eta.strip()
        return value or None

    @property
    def has_supporting_detail(self) -> bool:
        return any(
            value is not None
            for value in (
                self.rationale,
                self.confirmation_signal,
                self.falsification_signal,
                self.estimated_duration,
            )
        )
