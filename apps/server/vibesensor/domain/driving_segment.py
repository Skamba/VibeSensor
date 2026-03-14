"""Meaningful portion of a test run used for interpretation."""

from __future__ import annotations

from dataclasses import dataclass

from .driving_phase import DrivingPhase

__all__ = ["DrivingSegment"]


@dataclass(frozen=True, slots=True)
class DrivingSegment:
    """Phase-aligned segment of a run."""

    phase: DrivingPhase
    start_idx: int
    end_idx: int
    start_t_s: float | None = None
    end_t_s: float | None = None
    speed_min_kmh: float | None = None
    speed_max_kmh: float | None = None
    sample_count: int = 0

    @property
    def is_diagnostically_usable(self) -> bool:
        return self.sample_count > 0 and self.phase is not DrivingPhase.IDLE
