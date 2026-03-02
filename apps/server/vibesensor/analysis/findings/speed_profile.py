"""Speed-profile extraction and phase-string helpers."""

from __future__ import annotations

from ...runlog import as_float_or_none as _as_float
from ..helpers import (
    _amplitude_weighted_speed_window,
    _speed_bin_label,
    _weighted_percentile,
)


def _phase_to_str(phase: object) -> str | None:
    """Return the string value for a phase object (DrivingPhase or str)."""
    if phase is None:
        return None
    return phase.value if hasattr(phase, "value") else str(phase)


def _speed_profile_from_points(
    points: list[tuple[float, float]],
    *,
    allowed_speed_bins: list[str] | tuple[str, ...] | set[str] | None = None,
    phase_weights: list[float] | None = None,
) -> tuple[float | None, tuple[float, float] | None, str | None]:
    allowed = set(allowed_speed_bins) if allowed_speed_bins is not None else None
    indexed: list[tuple[float, float, float]] = []
    for idx, (speed, amp) in enumerate(points):
        if speed <= 0 or amp <= 0:
            continue
        if allowed is not None and _speed_bin_label(speed) not in allowed:
            continue
        phase_weight = 1.0
        if phase_weights is not None and idx < len(phase_weights):
            parsed_weight = _as_float(phase_weights[idx])
            if parsed_weight is not None and parsed_weight > 0:
                phase_weight = parsed_weight
        indexed.append((speed, amp, phase_weight))
    valid = [(speed, amp) for speed, amp, _phase_weight in indexed]

    if not valid:
        return None, None, None

    peak_speed_kmh = max(valid, key=lambda item: item[1])[0]
    low = _weighted_percentile(valid, 0.10)
    high = _weighted_percentile(valid, 0.90)
    if low is None or high is None:
        return peak_speed_kmh, None, None
    if high < low:
        low, high = high, low
    speed_window_kmh = (low, high)

    # Apply phase weights: multiply amplitude by phase weight so CRUISE
    # samples contribute more and ACCELERATION/ramp samples contribute less
    # to speed-band selection.
    effective_amps = [amp * phase_weight for _speed, amp, phase_weight in indexed]

    low_speed, high_speed = _amplitude_weighted_speed_window(
        [speed_kmh for speed_kmh, _amp in valid],
        effective_amps,
    )
    strongest_speed_band = (
        f"{low_speed:.0f}-{high_speed:.0f} km/h"
        if low_speed is not None and high_speed is not None
        else None
    )
    return peak_speed_kmh, speed_window_kmh, strongest_speed_band
