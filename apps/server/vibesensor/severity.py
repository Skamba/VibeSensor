"""Severity-bucket state tracking with hysteresis and persistence.

Tracks vibration severity over successive ticks, applying promotion/decay
thresholds, multi-sensor corroboration, and frequency-guard persistence.
"""

from __future__ import annotations

from typing import TypedDict

from vibesensor.strength_bands import (
    DECAY_TICKS,
    HYSTERESIS_DB,
    PERSISTENCE_TICKS,
    band_by_key,
    band_rank,
    bucket_for_strength,
)

from .constants import MULTI_SENSOR_CORROBORATION_DB
from .json_utils import as_float_or_none


class SeverityTrackerState(TypedDict):
    current_bucket: str | None
    pending_bucket: str | None
    consecutive_up: int
    consecutive_down: int
    last_confirmed_hz: float | None


class SeverityResult(TypedDict):
    key: str | None
    db: float
    state: SeverityTrackerState


_DEFAULT_SEVERITY_STATE: SeverityTrackerState = {
    "current_bucket": None,
    "pending_bucket": None,
    "consecutive_up": 0,
    "consecutive_down": 0,
    "last_confirmed_hz": None,
}


def severity_from_peak(
    *,
    vibration_strength_db: float,
    sensor_count: int,
    prior_state: SeverityTrackerState | None = None,
    peak_hz: float | None = None,
    persistence_freq_bin_hz: float | None = None,
) -> SeverityResult:
    """Compute the severity bucket and updated state for a peak measurement.

    Applies hysteresis, persistence, and multi-sensor corroboration before
    returning the new bucket and a ``"state"`` dict for subsequent calls.
    """
    state: SeverityTrackerState = {**_DEFAULT_SEVERITY_STATE, **(prior_state or {})}  # type: ignore[typeddict-item]
    corroboration = MULTI_SENSOR_CORROBORATION_DB if sensor_count >= 2 else 0.0
    adjusted_db = float(vibration_strength_db) + corroboration
    candidate_bucket_raw = bucket_for_strength(adjusted_db)
    candidate_bucket = None if candidate_bucket_raw == "l0" else candidate_bucket_raw
    current_bucket = state.get("current_bucket")
    peak_hz_value = as_float_or_none(peak_hz)
    freq_bin_hz = as_float_or_none(persistence_freq_bin_hz)
    freq_guard_enabled = peak_hz_value is not None and freq_bin_hz is not None and freq_bin_hz > 0

    def _advance_pending(candidate: str) -> None:
        pending = state.get("pending_bucket")
        if pending == candidate:
            if freq_guard_enabled:
                last_confirmed_hz = as_float_or_none(state.get("last_confirmed_hz"))
                assert peak_hz_value is not None and freq_bin_hz is not None
                if last_confirmed_hz is not None and abs(
                    float(peak_hz_value) - last_confirmed_hz,
                ) > float(freq_bin_hz):
                    state["consecutive_up"] = 1
                    state["last_confirmed_hz"] = peak_hz_value
                    return
                if last_confirmed_hz is None:
                    state["last_confirmed_hz"] = peak_hz_value
            state["consecutive_up"] = int(state.get("consecutive_up", 0)) + 1
            return

        state["pending_bucket"] = candidate
        state["consecutive_up"] = 1
        state["last_confirmed_hz"] = peak_hz_value if freq_guard_enabled else None

    def _try_promote(candidate: str) -> None:
        """Advance pending bucket and promote if persistence threshold is met."""
        state["consecutive_down"] = 0
        _advance_pending(candidate)
        if int(state["consecutive_up"]) >= PERSISTENCE_TICKS:
            state["current_bucket"] = candidate
            state["pending_bucket"] = None
            state["consecutive_up"] = 0
            if freq_guard_enabled:
                state["last_confirmed_hz"] = peak_hz_value

    if candidate_bucket is None:
        if current_bucket is not None:
            current_band = band_by_key(str(current_bucket))
            if current_band and adjusted_db < float(current_band["min_db"]) - HYSTERESIS_DB:
                state["consecutive_down"] = int(state.get("consecutive_down", 0)) + 1
                if int(state["consecutive_down"]) >= DECAY_TICKS:
                    state["current_bucket"] = None
                    state["pending_bucket"] = None
                    state["consecutive_down"] = 0
                    state["consecutive_up"] = 0
                    state["last_confirmed_hz"] = None
            else:
                state["consecutive_down"] = 0
        return {"key": state.get("current_bucket"), "db": adjusted_db, "state": state}

    if current_bucket is None:
        _try_promote(candidate_bucket)
        return {"key": state.get("current_bucket"), "db": adjusted_db, "state": state}

    current_rank = band_rank(str(current_bucket))
    candidate_rank = band_rank(str(candidate_bucket))
    if candidate_rank > current_rank:
        _try_promote(candidate_bucket)
    elif candidate_rank < current_rank:
        current_band = band_by_key(str(current_bucket))
        if current_band and adjusted_db < float(current_band["min_db"]) - HYSTERESIS_DB:
            state["consecutive_down"] = int(state.get("consecutive_down", 0)) + 1
            if int(state["consecutive_down"]) >= DECAY_TICKS:
                state["current_bucket"] = candidate_bucket
                state["pending_bucket"] = None
                state["consecutive_down"] = 0
                state["consecutive_up"] = 0
                state["last_confirmed_hz"] = None
        else:
            state["consecutive_down"] = 0
    else:
        state["pending_bucket"] = None
        state["consecutive_up"] = 0
        state["last_confirmed_hz"] = None

    return {"key": state.get("current_bucket"), "db": adjusted_db, "state": state}
