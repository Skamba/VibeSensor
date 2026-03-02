"""Active level management — tracking dominant severity by source, sensor, and location."""

from __future__ import annotations

from typing import Any

from ..constants import SILENCE_DB
from ..diagnostics_shared import source_keys_from_class_key
from ._types import _TrackerLevelState


def upsert_active_level(
    *,
    active_by_source: dict[str, dict[str, Any]],
    source_keys: tuple[str, ...],
    bucket_key: str,
    strength_db: float,
    sensor_label: str,
    sensor_location: str,
    class_key: str,
    peak_hz: float,
) -> None:
    for source_key in source_keys:
        existing = active_by_source.get(source_key)
        if existing is None or strength_db > float(existing.get("strength_db", -1e9)):
            active_by_source[source_key] = {
                "bucket_key": bucket_key,
                "strength_db": strength_db,
                "sensor_label": sensor_label,
                "sensor_location": sensor_location,
                "class_key": class_key,
                "peak_hz": peak_hz,
            }


def update_sensor_active_level(
    active_by_sensor: dict[str, dict[str, Any]],
    sensor_id: str,
    *,
    bucket_key: str,
    strength_db: float,
    class_key: str,
    peak_hz: float,
) -> None:
    """Keep only the strongest active level per sensor."""
    existing = active_by_sensor.get(sensor_id)
    if existing is None or strength_db > float(existing.get("strength_db", -1e9)):
        active_by_sensor[sensor_id] = {
            "bucket_key": bucket_key,
            "strength_db": strength_db,
            "class_key": class_key,
            "peak_hz": peak_hz,
        }


def location_key(sensor_location: str) -> str | None:
    key = str(sensor_location or "").strip()
    return key or None


def build_active_levels_by_location(
    *,
    candidates_by_location: dict[str, list[dict[str, Any]]],
    freq_bin_hz: float,
) -> dict[str, dict[str, Any]]:
    by_location: dict[str, dict[str, Any]] = {}
    for location_key_val, candidates in candidates_by_location.items():
        if not candidates:
            continue
        dominant = max(candidates, key=lambda row: float(row.get("strength_db", SILENCE_DB)))
        dominant_bin = (
            str(dominant.get("class_key") or ""),
            str(dominant.get("bucket_key") or ""),
            int(round(float(dominant.get("peak_hz") or 0.0) / max(0.01, freq_bin_hz))),
        )
        agreeing_ids = {
            str(row.get("sensor_id") or "")
            for row in candidates
            if (
                str(row.get("class_key") or ""),
                str(row.get("bucket_key") or ""),
                int(round(float(row.get("peak_hz") or 0.0) / max(0.01, freq_bin_hz))),
            )
            == dominant_bin
            and str(row.get("sensor_id") or "")
        }
        agreement_count = len(agreeing_ids)
        confidence = 1.0 + max(0, agreement_count - 1)
        by_location[location_key_val] = {
            "bucket_key": str(dominant.get("bucket_key") or ""),
            "strength_db": float(dominant.get("strength_db", SILENCE_DB)),
            "sensor_label": str(dominant.get("sensor_label") or ""),
            "sensor_location": location_key_val,
            "class_key": str(dominant.get("class_key") or ""),
            "peak_hz": float(dominant.get("peak_hz") or 0.0),
            "confidence": float(confidence),
            "agreement_count": agreement_count,
            "sensor_count": len(
                {
                    str(row.get("sensor_id") or "")
                    for row in candidates
                    if str(row.get("sensor_id") or "")
                }
            ),
        }
    return by_location


def collect_active_levels_from_trackers(
    sensor_trackers: dict[str, _TrackerLevelState],
    active_by_source: dict[str, dict[str, Any]],
    active_by_sensor: dict[str, dict[str, Any]],
    location_candidates: dict[str, list[dict[str, Any]]],
) -> None:
    """Rebuild source/sensor/location active levels from all tracker state."""
    for tracker_key, tracker in sensor_trackers.items():
        if tracker.current_bucket_key is None:
            continue
        sensor_id, _, class_key = tracker_key.partition(":")
        source_keys = source_keys_from_class_key(class_key or tracker.last_class_key)
        upsert_active_level(
            active_by_source=active_by_source,
            source_keys=source_keys,
            bucket_key=tracker.current_bucket_key,
            strength_db=tracker.last_strength_db,
            sensor_label=tracker.last_sensor_label,
            sensor_location=tracker.last_sensor_location,
            class_key=class_key or tracker.last_class_key,
            peak_hz=tracker.last_peak_hz,
        )
        update_sensor_active_level(
            active_by_sensor,
            sensor_id,
            bucket_key=tracker.current_bucket_key,
            strength_db=tracker.last_strength_db,
            class_key=class_key or tracker.last_class_key,
            peak_hz=tracker.last_peak_hz,
        )
        loc_key = location_key(tracker.last_sensor_location)
        if loc_key:
            location_candidates.setdefault(loc_key, []).append(
                {
                    "sensor_id": sensor_id,
                    "sensor_label": tracker.last_sensor_label,
                    "bucket_key": tracker.current_bucket_key,
                    "strength_db": tracker.last_strength_db,
                    "class_key": class_key or tracker.last_class_key,
                    "peak_hz": tracker.last_peak_hz,
                }
            )
