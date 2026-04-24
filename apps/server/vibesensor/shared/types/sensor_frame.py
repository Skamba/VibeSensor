"""Canonical typed sample record shared across recording and persistence."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.domain import StrengthPeak

__all__ = ["SensorFrame"]


@dataclass(slots=True)
class SensorFrame:
    """A single sample record shared by run recording and persistence.

    ``top_peaks`` stays typed as :class:`StrengthPeak` objects internally and
    is serialized back to JSON payload dicts only at explicit boundaries.
    """

    run_id: str
    timestamp_utc: str
    t_s: float | None
    client_id: str
    client_name: str
    location: str
    sample_rate_hz: int | None
    speed_kmh: float | None
    gps_speed_kmh: float | None
    speed_source: str
    engine_rpm: float | None
    engine_rpm_source: str
    gear: float | None
    final_drive_ratio: float | None
    accel_x_g: float | None
    accel_y_g: float | None
    accel_z_g: float | None
    dominant_freq_hz: float | None
    dominant_axis: str
    top_peaks: tuple[StrengthPeak, ...]
    vibration_strength_db: float | None
    strength_bucket: str | None
    strength_peak_amp_g: float | None
    strength_floor_amp_g: float | None
    frames_dropped_total: int
    queue_overflow_drops: int
    analysis_window_start_us: int | None = None
    analysis_window_end_us: int | None = None
    analysis_window_synced: bool | None = None
