"""Project low-level report payload fields into normalized helper values."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from vibesensor.domain import coerce_float, coerce_int
from vibesensor.shared.boundaries.run_metadata_codec import run_metadata_from_mapping
from vibesensor.shared.types.analysis_views import PeakTableRow
from vibesensor.shared.types.history_analysis_contracts import PhaseTimelineEntryResponse
from vibesensor.shared.types.run_schema import RunMetadata

__all__ = [
    "active_sensor_locations",
    "coerce_count",
    "phase_timeline_payload",
    "peak_table_rows",
    "report_duration_s",
    "sensor_intensity_payload",
    "summary_run_metadata",
]


def summary_run_metadata(payload: Mapping[str, object]) -> RunMetadata | None:
    """Return canonical typed run metadata when one summary metadata block exists."""

    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    normalized_metadata = dict(metadata)
    raw_run_id = str(payload.get("run_id") or "").strip()
    if raw_run_id and "run_id" not in normalized_metadata:
        normalized_metadata["run_id"] = raw_run_id
    return run_metadata_from_mapping(normalized_metadata) if normalized_metadata else None


def active_sensor_locations(payload: Mapping[str, object]) -> tuple[str, ...]:
    """Return active sensor locations, preferring the connected-throughout list."""
    connected = payload.get("sensor_locations_connected_throughout")
    locations = connected if isinstance(connected, list) else []
    active = tuple(str(loc).strip() for loc in locations if str(loc).strip())
    if active:
        return active
    fallback = payload.get("sensor_locations")
    fallback_locations = fallback if isinstance(fallback, list) else []
    return tuple(str(loc).strip() for loc in fallback_locations if str(loc).strip())


def report_duration_s(payload: Mapping[str, object]) -> float | None:
    """Return a coerced report duration in seconds, or ``None`` for invalid input."""
    duration_s_raw = payload.get("duration_s")
    if duration_s_raw is None:
        return None
    try:
        return coerce_float(duration_s_raw)
    except (TypeError, ValueError):
        return None


def peak_table_rows(payload: Mapping[str, object]) -> tuple[PeakTableRow, ...]:
    """Return normalized peak-table rows from the plots payload."""
    plots = payload.get("plots")
    if not isinstance(plots, Mapping):
        return ()
    raw_peaks = plots.get("peaks_table")
    if not isinstance(raw_peaks, list):
        return ()
    return tuple(cast(PeakTableRow, row) for row in raw_peaks if isinstance(row, Mapping))


def sensor_intensity_payload(payload: Mapping[str, object]) -> tuple[object, ...]:
    """Return the sensor-intensity payload as an immutable tuple copy."""
    raw_sensor_intensity = payload.get("sensor_intensity_by_location")
    if not isinstance(raw_sensor_intensity, list):
        return ()
    return tuple(raw_sensor_intensity)


def phase_timeline_payload(payload: Mapping[str, object]) -> tuple[PhaseTimelineEntryResponse, ...]:
    """Return normalized phase-timeline rows from the summary payload."""
    raw_phase_timeline = payload.get("phase_timeline")
    if not isinstance(raw_phase_timeline, list):
        return ()
    return tuple(
        cast(PhaseTimelineEntryResponse, row)
        for row in raw_phase_timeline
        if isinstance(row, Mapping)
    )


def coerce_count(value: object) -> int:
    """Coerce count-like values to ``int``, defaulting invalid inputs to zero."""
    if value is None:
        return 0
    try:
        return coerce_int(value)
    except (TypeError, ValueError):
        return 0
