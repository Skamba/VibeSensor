"""A contiguous aligned chunk of samples used by the analysis pipeline.

``AnalysisWindow`` represents the temporal and phase context of one analysis
unit — a segment of the run where driving conditions are sufficiently
uniform for meaningful spectral and order analysis.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "AnalysisWindow",
]


@dataclass(frozen=True, slots=True)
class AnalysisWindow:
    """A contiguous aligned chunk of samples used by the analysis pipeline.

    Represents the temporal and phase context of one analysis unit —
    a segment of the run where driving conditions are sufficiently
    uniform for meaningful spectral and order analysis.

    Phase classification
    --------------------
    Phase strings follow the ``DrivingPhase`` enum values: ``"cruise"``,
    ``"acceleration"``, ``"deceleration"``, ``"idle"``, ``"unknown"``.
    """

    start_idx: int
    end_idx: int
    phase: str = ""
    start_time_s: float | None = None
    end_time_s: float | None = None
    speed_min_kmh: float | None = None
    speed_max_kmh: float | None = None

    # -- queries -----------------------------------------------------------

    @property
    def sample_count(self) -> int:
        """Number of samples in this window."""
        return max(0, self.end_idx - self.start_idx)

    @property
    def duration_s(self) -> float | None:
        """Duration of the window in seconds, or None if timestamps are missing."""
        if self.start_time_s is not None and self.end_time_s is not None:
            return self.end_time_s - self.start_time_s
        return None

    # -- phase classification ----------------------------------------------

    @property
    def is_cruising(self) -> bool:
        """Whether this window represents a constant-speed cruise phase."""
        return self.phase.strip().lower() == "cruise"

    @property
    def is_acceleration(self) -> bool:
        return self.phase.strip().lower() == "acceleration"

    @property
    def is_deceleration(self) -> bool:
        return self.phase.strip().lower() == "deceleration"

    @property
    def is_idle(self) -> bool:
        return self.phase.strip().lower() == "idle"

    # -- validity / filtering ----------------------------------------------

    @property
    def is_analyzable(self) -> bool:
        """Whether this window has enough samples for meaningful analysis."""
        return self.sample_count > 0

    def contains_speed(self, speed_kmh: float) -> bool:
        """Whether *speed_kmh* falls within this window's speed range."""
        lo = self.speed_min_kmh
        hi = self.speed_max_kmh
        if lo is None or hi is None:
            return False
        return lo <= speed_kmh <= hi

    # -- display -----------------------------------------------------------

    @property
    def speed_range_text(self) -> str | None:
        """Formatted speed range, e.g. ``'80–100 km/h'``, or ``None``."""
        if self.speed_min_kmh is not None and self.speed_max_kmh is not None:
            return f"{self.speed_min_kmh:.0f}\u2013{self.speed_max_kmh:.0f} km/h"
        return None
