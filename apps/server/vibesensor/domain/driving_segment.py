"""Driving phase and segment — tightly coupled driving classification types.

Co-locates DrivingPhase (the classification enum) and DrivingSegment
(the data container for a classified portion of a run).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = ["DrivingPhase", "DrivingSegment"]


# ---------------------------------------------------------------------------
# DrivingPhase
# ---------------------------------------------------------------------------


class DrivingPhase(StrEnum):
    """Canonical driving-phase labels."""

    IDLE = "idle"
    ACCELERATION = "acceleration"
    CRUISE = "cruise"
    DECELERATION = "deceleration"
    COAST_DOWN = "coast_down"
    SPEED_UNKNOWN = "speed_unknown"


# ---------------------------------------------------------------------------
# DrivingSegment
# ---------------------------------------------------------------------------

_MIN_USABLE_SAMPLES = 10


@dataclass(frozen=True, slots=True)
class DrivingSegment:
    """Phase-aligned segment of a run."""

    phase: DrivingPhase
    start_idx: int | None = None
    end_idx: int | None = None
    start_t_s: float | None = None
    end_t_s: float | None = None
    speed_min_kmh: float | None = None
    speed_max_kmh: float | None = None
    sample_count: int = 0

    @property
    def duration_s(self) -> float | None:
        """Duration of the segment in seconds, or None if timestamps are missing."""
        if self.start_t_s is not None and self.end_t_s is not None:
            return self.end_t_s - self.start_t_s
        return None

    @property
    def is_cruise(self) -> bool:
        return self.phase is DrivingPhase.CRUISE

    @property
    def is_diagnostically_usable(self) -> bool:
        """Whether this segment can contribute to diagnostic conclusions."""
        return self.sample_count >= _MIN_USABLE_SAMPLES and self.phase is not DrivingPhase.IDLE
