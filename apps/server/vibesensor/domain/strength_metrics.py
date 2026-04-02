"""Domain value objects for vibration strength measurement results."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["StrengthMetrics", "StrengthPeak"]


# ---------------------------------------------------------------------------
# StrengthPeak
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StrengthPeak:
    """A single identified vibration peak."""

    hz: float = 0.0
    amp: float = 0.0
    vibration_strength_db: float | None = None
    strength_bucket: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.hz > 0.0 and self.amp > 0.0


# ---------------------------------------------------------------------------
# StrengthMetrics
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StrengthMetrics:
    """Full strength-measurement summary for one finding or segment."""

    vibration_strength_db: float | None = None
    peak_amp_g: float | None = None
    noise_floor_amp_g: float | None = None
    strength_bucket: str | None = None
    top_peaks: tuple[StrengthPeak, ...] = ()

    @property
    def dominant_peak(self) -> StrengthPeak | None:
        return self.top_peaks[0] if self.top_peaks else None

    @property
    def dominant_hz(self) -> float | None:
        peak = self.dominant_peak
        if peak is None or peak.hz <= 0.0:
            return None
        return peak.hz
