"""Run speed behaviour as a diagnostic concept.

``SpeedProfile`` captures how the vehicle was driven during a
diagnostic run: average speed, range, steadiness, and cruise coverage.
These are domain-level concerns that affect diagnosis quality and
finding confidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

__all__ = ["SpeedProfile"]


@dataclass(frozen=True, slots=True)
class SpeedProfile:
    """Speed behaviour during a diagnostic run."""

    _MIN_DIAGNOSTIC_SAMPLES: ClassVar[int] = 10
    _MIN_DIAGNOSTIC_SPEED_KMH: ClassVar[float] = 5.0
    _MIN_STEADY_CRUISE_FRACTION: ClassVar[float] = 0.3

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

    # -- domain queries ----------------------------------------------------

    @property
    def speed_range_kmh(self) -> float:
        """Total speed range covered during the run."""
        return max(0.0, self.max_kmh - self.min_kmh)

    @property
    def is_adequate_for_diagnosis(self) -> bool:
        """Enough speed data exists for meaningful analysis."""
        return (
            self.sample_count >= self._MIN_DIAGNOSTIC_SAMPLES
            and self.max_kmh > self._MIN_DIAGNOSTIC_SPEED_KMH
        )

    @property
    def known_speed_fraction(self) -> float:
        """Fraction of samples with a known vehicle speed."""
        return min(1.0, max(0.0, 1.0 - self.speed_unknown_fraction))

    @property
    def driving_fraction(self) -> float:
        """Fraction of samples spent in a moving, diagnostically useful state."""
        return min(1.0, max(0.0, 1.0 - self.idle_fraction))

    @property
    def has_steady_cruise(self) -> bool:
        """Run had meaningful cruise segments (best evidence quality)."""
        return self.has_cruise and self.cruise_fraction >= self._MIN_STEADY_CRUISE_FRACTION

    @property
    def has_speed_variation(self) -> bool:
        """Run includes meaningful variable-speed behaviour for diagnosis."""
        return self.has_acceleration or (not self.steady_speed and self.speed_range_kmh > 0.0)

    @property
    def supports_variable_speed_diagnosis(self) -> bool:
        """Run has enough variable-speed evidence to support speed-dependent reasoning."""
        return self.is_adequate_for_diagnosis and self.has_speed_variation

    @property
    def supports_steady_state_diagnosis(self) -> bool:
        """Run has enough stable-speed evidence to support steady-state reasoning."""
        return self.is_adequate_for_diagnosis and (
            self.has_steady_cruise or (self.steady_speed and self.driving_fraction > 0.0)
        )
