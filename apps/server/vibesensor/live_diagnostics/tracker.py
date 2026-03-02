"""Severity tracking — hysteresis, emission decisions, and bucket transitions."""

from __future__ import annotations

from vibesensor_core.strength_bands import band_rank

from ..diagnostics_shared import severity_from_peak
from ._types import _TrackerLevelState


def apply_severity_to_tracker(
    tracker: _TrackerLevelState,
    vibration_strength_db: float,
    sensor_count: int,
    freq_bin_hz: float,
    fallback_db: float | None = None,
) -> str | None:
    """Apply severity_from_peak to a tracker, updating its state in-place.

    Returns the previous bucket key so callers can detect transitions.
    """
    previous_bucket = tracker.current_bucket_key
    severity = severity_from_peak(
        vibration_strength_db=vibration_strength_db,
        sensor_count=sensor_count,
        prior_state=tracker.severity_state,
        peak_hz=tracker.last_peak_hz if tracker.last_peak_hz > 0 else None,
        persistence_freq_bin_hz=freq_bin_hz,
    )
    tracker.severity_state = dict((severity or {}).get("state") or tracker.severity_state or {})
    tracker.current_bucket_key = str(severity["key"]) if severity and severity.get("key") else None
    _sev_db = (severity or {}).get("db")
    tracker.last_strength_db = float(
        _sev_db
        if _sev_db is not None
        else (fallback_db if fallback_db is not None else vibration_strength_db)
    )
    return previous_bucket


def should_emit_event(
    tracker: _TrackerLevelState,
    previous_bucket: str | None,
    current_bucket: str | None,
    now_ms: int,
    heartbeat_ms: int,
) -> bool:
    if current_bucket is None:
        return False
    prev_rank = band_rank(previous_bucket or "")
    cur_rank = band_rank(current_bucket)
    if previous_bucket is None or cur_rank > prev_rank:
        return True
    return now_ms - tracker.last_emitted_ms >= heartbeat_ms


def matrix_transition_bucket(
    previous_bucket: str | None,
    current_bucket: str | None,
) -> str | None:
    if current_bucket is None:
        return None
    if previous_bucket is None:
        return current_bucket
    if band_rank(current_bucket) > band_rank(previous_bucket):
        return current_bucket
    return None
