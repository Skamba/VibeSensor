"""Active level management — tracking dominant severity by source, sensor, and location."""

from __future__ import annotations

from ..constants import SILENCE_DB
from ..diagnostics_shared import source_keys_from_class_key
from ._types import (
    ActiveLevelsByKey,
    LocationCandidatePayload,
    LocationCandidatesByKey,
    _TrackerLevelState,
)

# Sentinel used for "no existing strength" comparisons — avoids repeated
# dict.get default-value allocation on every call.
_NEG_INF = float("-inf")


def upsert_active_level(
    *,
    active_by_source: ActiveLevelsByKey,
    source_keys: tuple[str, ...],
    bucket_key: str,
    strength_db: float,
    sensor_label: str,
    sensor_location: str,
    class_key: str,
    peak_hz: float,
) -> None:
    """Insert or replace the active level for each key in *source_keys*.

    The new entry replaces an existing one only if *strength_db* is
    strictly greater, keeping the strongest level per source.
    """
    _get = active_by_source.get
    for source_key in source_keys:
        existing = _get(source_key)
        if existing is None or strength_db > existing.get("strength_db", _NEG_INF):
            active_by_source[source_key] = {
                "bucket_key": bucket_key,
                "strength_db": strength_db,
                "sensor_label": sensor_label,
                "sensor_location": sensor_location,
                "class_key": class_key,
                "peak_hz": peak_hz,
            }


def update_sensor_active_level(
    active_by_sensor: ActiveLevelsByKey,
    sensor_id: str,
    *,
    bucket_key: str,
    strength_db: float,
    class_key: str,
    peak_hz: float,
) -> None:
    """Keep only the strongest active level per sensor."""
    existing = active_by_sensor.get(sensor_id)
    if existing is None or strength_db > existing.get("strength_db", _NEG_INF):
        active_by_sensor[sensor_id] = {
            "bucket_key": bucket_key,
            "strength_db": strength_db,
            "class_key": class_key,
            "peak_hz": peak_hz,
        }


def location_key(sensor_location: str) -> str | None:
    """Return a normalised location key, or ``None`` for blank/empty strings."""
    key = str(sensor_location or "").strip()
    return key or None


def _row_bin(row: LocationCandidatePayload, inv_bin: float) -> tuple[str, str, int]:
    """Compute the (class_key, bucket_key, freq_bin_index) tuple for *row*."""
    return (
        str(row.get("class_key") or ""),
        str(row.get("bucket_key") or ""),
        round(float(row.get("peak_hz") or 0.0) * inv_bin),
    )


def build_active_levels_by_location(
    *,
    candidates_by_location: LocationCandidatesByKey,
    freq_bin_hz: float,
) -> ActiveLevelsByKey:
    """Aggregate candidate rows per location, keeping the strongest per frequency bin."""
    by_location: ActiveLevelsByKey = {}
    # Pre-compute reciprocal once; multiplication is cheaper than division
    # inside the per-candidate inner loop.
    inv_bin = 1.0 / max(0.01, freq_bin_hz)
    _bin = _row_bin  # local binding avoids global lookup per candidate

    for location_key_val, candidates in candidates_by_location.items():
        if not candidates:
            continue
        dominant = max(candidates, key=lambda row: float(row.get("strength_db", SILENCE_DB)))
        dominant_bin = _bin(dominant, inv_bin)

        # Single pass: collect agreeing sensor IDs *and* all unique sensor IDs.
        agreeing_ids: set[str] = set()
        all_sensor_ids: set[str] = set()
        for row in candidates:
            sid = str(row.get("sensor_id") or "")
            if sid:
                all_sensor_ids.add(sid)
                if _bin(row, inv_bin) == dominant_bin:
                    agreeing_ids.add(sid)

        agreement_count = len(agreeing_ids)
        by_location[location_key_val] = {
            "bucket_key": str(dominant.get("bucket_key") or ""),
            "strength_db": float(dominant.get("strength_db", SILENCE_DB)),
            "sensor_label": str(dominant.get("sensor_label") or ""),
            "sensor_location": location_key_val,
            "class_key": str(dominant.get("class_key") or ""),
            "peak_hz": float(dominant.get("peak_hz") or 0.0),
            "confidence": float(1.0 + max(0, agreement_count - 1)),
            "agreement_count": agreement_count,
            "sensor_count": len(all_sensor_ids),
        }
    return by_location


def collect_active_levels_from_trackers(
    sensor_trackers: dict[str, _TrackerLevelState],
    active_by_source: ActiveLevelsByKey,
    active_by_sensor: ActiveLevelsByKey,
    location_candidates: LocationCandidatesByKey,
) -> None:
    """Rebuild source/sensor/location active levels from all tracker state."""
    for tracker_key, tracker in sensor_trackers.items():
        bucket_key = tracker.current_bucket_key
        if bucket_key is None:
            continue
        sensor_id, _, raw_class_key = tracker_key.partition(":")
        resolved_class_key = raw_class_key or tracker.last_class_key

        source_keys = source_keys_from_class_key(resolved_class_key)
        strength_db = tracker.last_strength_db
        peak_hz = tracker.last_peak_hz

        upsert_active_level(
            active_by_source=active_by_source,
            source_keys=source_keys,
            bucket_key=bucket_key,
            strength_db=strength_db,
            sensor_label=tracker.last_sensor_label,
            sensor_location=tracker.last_sensor_location,
            class_key=resolved_class_key,
            peak_hz=peak_hz,
        )
        update_sensor_active_level(
            active_by_sensor,
            sensor_id,
            bucket_key=bucket_key,
            strength_db=strength_db,
            class_key=resolved_class_key,
            peak_hz=peak_hz,
        )
        loc_key = location_key(tracker.last_sensor_location)
        if loc_key:
            location_candidates.setdefault(loc_key, []).append(
                {
                    "sensor_id": sensor_id,
                    "sensor_label": tracker.last_sensor_label,
                    "bucket_key": bucket_key,
                    "strength_db": strength_db,
                    "class_key": resolved_class_key,
                    "peak_hz": peak_hz,
                }
            )
