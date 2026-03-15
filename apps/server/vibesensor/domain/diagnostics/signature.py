"""Coherent vibration pattern assembled from observations."""

from __future__ import annotations

from dataclasses import dataclass

from .finding import VibrationSource

__all__ = ["Signature"]


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
