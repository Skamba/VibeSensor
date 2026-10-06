from __future__ import annotations

from dataclasses import dataclass

__all__ = ["AnalysisTimeRange"]


@dataclass(frozen=True, slots=True)
class AnalysisTimeRange:
    """Absolute monotonic analysis-window range for the latest computed metrics.

    ``centre_s`` is the time the spectrum describes: where the block's samples
    present weigh in under the FFT window (``present_centre``), the midpoint
    unless frames were lost.
    """

    start_s: float
    end_s: float
    synced: bool
    centre_s: float
