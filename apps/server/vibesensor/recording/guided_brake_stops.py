"""Live count of the firm stops in the guided test drive's brake step.

The brake step asks the driver to brake firmly a few times, so the analysis has
enough braking spectra to judge brake judder. The Live page shows how many
stops count so far. A stop counts by the analysis's own rule
(``braking_intervals`` in ``analysis/phase_segmentation.py``, "Braking" in
docs/analysis_pipeline.md), applied to the speed the recording stores, so a stop
counted here is one the analysis finds braking in.
"""

from __future__ import annotations

from vibesensor.analysis.phase_segmentation import (
    BRAKING_SETTLED_AFTER_S,
    braking_intervals,
    speed_slopes_kmh_s,
)

__all__ = ["GuidedBrakeStops"]

# No braking spell lasts this long (0.2 g for 60 s sheds over 400 km/h), so
# older readings never decide a stop still to be counted.
_KEEP_S = 60.0


class GuidedBrakeStops:
    """Counts the firm stops in the speed readings of the guided brake step."""

    def __init__(self) -> None:
        self._series: list[tuple[float, float]] = []
        self._counted = 0
        self._counted_until_s = float("-inf")

    @property
    def count(self) -> int:
        return self._counted

    def observe(self, t_s: float, speed_kmh: float) -> None:
        """Add the speed reading at *t_s* and count the stops it settles."""
        if self._series and t_s <= self._series[-1][0]:
            return
        self._series.append((t_s, speed_kmh))
        settled = [
            (start_s, end_s)
            for start_s, end_s in braking_intervals(self._series, speed_slopes_kmh_s(self._series))
            if start_s > self._counted_until_s and end_s + BRAKING_SETTLED_AFTER_S <= t_s
        ]
        if settled:
            self._counted += len(settled)
            self._counted_until_s = settled[-1][1]
        # Readings this old cannot change the slope of any reading after the
        # last counted stop, so the series stays short however long the step is.
        keep_from_s = max(self._counted_until_s - BRAKING_SETTLED_AFTER_S, t_s - _KEEP_S)
        while self._series[0][0] < keep_from_s:
            self._series.pop(0)
