"""Complaint framing for a diagnostic case."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Symptom"]


@dataclass(frozen=True, slots=True)
class Symptom:
    """The complaint or observed problem motivating diagnosis."""

    description: str
    onset: str = ""
    context: str = ""

    @classmethod
    def unspecified(cls) -> Symptom:
        return cls(description="unspecified complaint")

    @property
    def is_unspecified(self) -> bool:
        return self.description.strip().lower() == "unspecified complaint"

    @property
    def is_speed_dependent(self) -> bool:
        text = f"{self.description} {self.context}".lower()
        return any(token in text for token in ("speed", "km/h", "cruise", "driving"))

    @property
    def is_transient(self) -> bool:
        text = f"{self.description} {self.context} {self.onset}".lower()
        return any(token in text for token in ("intermittent", "transient", "sometimes"))
