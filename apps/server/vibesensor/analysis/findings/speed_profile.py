"""Speed-profile extraction and phase-string helpers."""

from __future__ import annotations

from ...runlog import as_float_or_none as _as_float
from ..helpers import (
    _amplitude_weighted_speed_window,
    _speed_bin_label,
    _weighted_percentile,
)

_SENTINEL = object()


def _phase_to_str(phase: object) -> str | None:
    """Return the string value for a phase object (DrivingPhase or str)."""
    if phase is None:
        return None
    val = getattr(phase, "value", _SENTINEL)
    return val if val is not _SENTINEL else str(phase)


def _speed_profile_from_points(
    points: list[tuple[float, float]],
    *,
    allowed_speed_bins: list[str] | tuple[str, ...] | set[str] | None = None,
    phase_weights: list[float] | None = None,
) -> tuple[float | None, tuple[float, float] | None, str | None]:
    allowed = set(allowed_speed_bins) if allowed_speed_bins is not None else None

    # Local-bind helpers used in the hot loop
    _bin_label = _speed_bin_label
    _float_or_none = _as_float

    # Single pass: build valid pairs, effective_amps, and speeds lists together,
    # avoiding an intermediate 'indexed' list and redundant re-iterations.
    valid: list[tuple[float, float]] = []
    effective_amps: list[float] = []
    speeds: list[float] = []
    has_weights = phase_weights is not None
    n_weights = len(phase_weights) if has_weights else 0

    for idx, (speed, amp) in enumerate(points):
        if speed <= 0 or amp <= 0:
            continue
        if allowed is not None and _bin_label(speed) not in allowed:
            continue
        phase_weight = 1.0
        if has_weights and idx < n_weights:
            parsed_weight = _float_or_none(phase_weights[idx])  # type: ignore[index]
            if parsed_weight is not None and parsed_weight > 0:
                phase_weight = parsed_weight
        valid.append((speed, amp))
        effective_amps.append(amp * phase_weight)
        speeds.append(speed)

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

    low_speed, high_speed = _amplitude_weighted_speed_window(
        speeds,
        effective_amps,
    )
    strongest_speed_band = (
        f"{low_speed:.0f}-{high_speed:.0f} km/h"
        if low_speed is not None and high_speed is not None
        else None
    )
    return peak_speed_kmh, speed_window_kmh, strongest_speed_band
