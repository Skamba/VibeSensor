"""Driving-phase summary snapshot used for reconstruction and interpretation."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType

from .driving_segment import DrivingPhaseSegment

__all__ = ["DrivingPhaseSummary"]


@dataclass(frozen=True, slots=True)
class DrivingPhaseSummary:
    """Typed internal phase-summary snapshot for reconstruction support."""

    phase_counts: dict[str, int] = field(default_factory=dict)
    phase_pcts: dict[str, float] = field(default_factory=dict)
    total_samples: int = 0
    segment_count: int = 0
    has_cruise: bool = False
    has_acceleration: bool = False
    cruise_pct: float = 0.0
    idle_pct: float = 0.0
    speed_unknown_pct: float = 0.0
    phase_type_summaries: tuple[DrivingPhaseSegment, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.phase_counts, MappingProxyType):
            object.__setattr__(self, "phase_counts", MappingProxyType(dict(self.phase_counts)))
        if not isinstance(self.phase_pcts, MappingProxyType):
            object.__setattr__(self, "phase_pcts", MappingProxyType(dict(self.phase_pcts)))
