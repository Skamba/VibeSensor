"""Speed-summary snapshot used for reconstruction and interpretation."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["SpeedProfileSummary"]


@dataclass(frozen=True, slots=True)
class SpeedProfileSummary:
    """Typed internal speed-summary snapshot for reconstruction support."""

    min_kmh: float | None = None
    max_kmh: float | None = None
    mean_kmh: float | None = None
    stddev_kmh: float | None = None
    range_kmh: float | None = None
    steady_speed: bool = False
    sample_count: int = 0
