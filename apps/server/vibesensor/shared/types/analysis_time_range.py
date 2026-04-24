from __future__ import annotations

from dataclasses import dataclass

__all__ = ["AnalysisTimeRange"]


@dataclass(frozen=True, slots=True)
class AnalysisTimeRange:
    """Absolute monotonic analysis-window range for the latest computed metrics."""

    start_s: float
    end_s: float
    synced: bool
