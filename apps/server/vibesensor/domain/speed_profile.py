"""Run speed behaviour as a diagnostic concept.

``SpeedProfile`` captures how the vehicle was driven during a
diagnostic run: average speed, range, steadiness, and cruise coverage.
These are domain-level concerns that affect diagnosis quality and
finding confidence.
"""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.domain.driving_phase_summary import DrivingPhaseSummary
from vibesensor.domain.speed_profile_summary import SpeedProfileSummary

__all__ = ["SpeedProfile"]


@dataclass(frozen=True, slots=True)
class SpeedProfile:
    """Speed behaviour during a diagnostic run."""

    min_kmh: float = 0.0
    max_kmh: float = 0.0
    mean_kmh: float = 0.0
    stddev_kmh: float = 0.0
    steady_speed: bool = False
    has_cruise: bool = False
    has_acceleration: bool = False
    cruise_fraction: float = 0.0
    idle_fraction: float = 0.0
    speed_unknown_fraction: float = 0.0
    sample_count: int = 0

    @classmethod
    def from_stats(
        cls,
        speed_stats: SpeedProfileSummary,
        phase_summary: DrivingPhaseSummary | None = None,
    ) -> SpeedProfile:
        """Construct a ``SpeedProfile`` from typed speed and phase snapshots."""
        phase = phase_summary or DrivingPhaseSummary()

        def _or_zero(value: float | None) -> float:
            return value if value is not None else 0.0

        def _fraction(percent: float | None) -> float:
            return min(1.0, max(0.0, percent / 100.0)) if percent else 0.0

        return cls(
            min_kmh=_or_zero(speed_stats.min_kmh),
            max_kmh=_or_zero(speed_stats.max_kmh),
            mean_kmh=_or_zero(speed_stats.mean_kmh),
            stddev_kmh=_or_zero(speed_stats.stddev_kmh),
            steady_speed=speed_stats.steady_speed,
            has_cruise=phase.has_cruise,
            has_acceleration=phase.has_acceleration,
            cruise_fraction=_fraction(phase.cruise_pct),
            idle_fraction=_fraction(phase.idle_pct),
            speed_unknown_fraction=_fraction(phase.speed_unknown_pct),
            sample_count=speed_stats.sample_count,
        )

    # -- domain queries ----------------------------------------------------

    @property
    def speed_range_kmh(self) -> float:
        """Total speed range covered during the run."""
        return max(0.0, self.max_kmh - self.min_kmh)
