"""Timed-observation helpers for aligning runtime data to analysis windows."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from math import isfinite

__all__ = [
    "DEFAULT_ALIGNMENT_TOLERANCE_S",
    "TimedObservationLookup",
    "TimedScalarObservation",
    "append_timed_observation",
    "resolve_timed_observation",
]

DEFAULT_ALIGNMENT_TOLERANCE_S = 1.0
_MAX_HISTORY_ITEMS = 128
_MAX_HISTORY_AGE_S = 30.0


@dataclass(frozen=True, slots=True)
class TimedScalarObservation:
    value: float
    monotonic_s: float


@dataclass(frozen=True, slots=True)
class TimedObservationLookup:
    value: float | None
    monotonic_s: float | None
    aligned: bool
    interpolated: bool = False


def append_timed_observation(
    history: tuple[TimedScalarObservation, ...],
    *,
    value: float | None,
    monotonic_s: float | None,
    now_s: float,
) -> tuple[TimedScalarObservation, ...]:
    threshold_s = now_s - _MAX_HISTORY_AGE_S
    pruned = tuple(obs for obs in history if obs.monotonic_s >= threshold_s)
    if value is None or monotonic_s is None or not isfinite(value) or not isfinite(monotonic_s):
        return pruned[-_MAX_HISTORY_ITEMS:]
    appended = (*pruned, TimedScalarObservation(value=float(value), monotonic_s=float(monotonic_s)))
    return appended[-_MAX_HISTORY_ITEMS:]


def resolve_timed_observation(
    history: tuple[TimedScalarObservation, ...],
    *,
    target_mono_s: float | None,
    tolerance_s: float = DEFAULT_ALIGNMENT_TOLERANCE_S,
) -> TimedObservationLookup:
    if target_mono_s is None or not history:
        return TimedObservationLookup(value=None, monotonic_s=None, aligned=False)
    timestamps = [obs.monotonic_s for obs in history]
    index = bisect_left(timestamps, target_mono_s)
    before = history[index - 1] if index > 0 else None
    after = history[index] if index < len(history) else None

    if before is not None and after is not None:
        if (
            abs(target_mono_s - before.monotonic_s) <= tolerance_s
            and abs(after.monotonic_s - target_mono_s) <= tolerance_s
            and after.monotonic_s > before.monotonic_s
        ):
            span = after.monotonic_s - before.monotonic_s
            ratio = (target_mono_s - before.monotonic_s) / span
            value = before.value + ((after.value - before.value) * ratio)
            return TimedObservationLookup(
                value=float(value),
                monotonic_s=float(target_mono_s),
                aligned=True,
                interpolated=True,
            )

    candidates = tuple(obs for obs in (before, after) if obs is not None)
    if not candidates:
        return TimedObservationLookup(value=None, monotonic_s=None, aligned=False)
    nearest = min(
        candidates,
        key=lambda obs: (abs(obs.monotonic_s - target_mono_s), obs.monotonic_s),
    )
    if abs(nearest.monotonic_s - target_mono_s) > tolerance_s:
        return TimedObservationLookup(value=None, monotonic_s=None, aligned=False)
    return TimedObservationLookup(
        value=float(nearest.value),
        monotonic_s=float(nearest.monotonic_s),
        aligned=True,
    )
