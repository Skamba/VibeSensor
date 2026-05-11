"""Primitive sensor sample builders for tests."""

from __future__ import annotations

from typing import Any

from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.types.sensor_frame import SensorFrame
from vibesensor.strength_bands import bucket_for_strength


def make_sample(
    *,
    t_s: float,
    speed_kmh: float,
    client_name: str,
    top_peaks: list[dict[str, float]] | None = None,
    vibration_strength_db: float = 15.0,
    strength_floor_amp_g: float = 0.003,
    accel_x_g: float = 0.02,
    accel_y_g: float = 0.02,
    accel_z_g: float = 0.10,
    engine_rpm: float | None = None,
    dominant_freq_hz: float | None = None,
    location: str = "",
    client_id: str | None = None,
    strength_peak_amp_g: float | None = None,
) -> dict[str, Any]:
    """Build a single JSONL-style sensor sample dict."""
    sample: dict[str, Any] = {
        "t_s": t_s,
        "speed_kmh": speed_kmh,
        "accel_x_g": accel_x_g,
        "accel_y_g": accel_y_g,
        "accel_z_g": accel_z_g,
        "vibration_strength_db": vibration_strength_db,
        "strength_bucket": bucket_for_strength(vibration_strength_db),
        "strength_floor_amp_g": strength_floor_amp_g,
        "client_name": client_name,
        "client_id": client_id or f"sensor-{client_name}",
        "top_peaks": top_peaks or [],
        "frames_dropped_total": 0,
        "queue_overflow_drops": 0,
    }
    if engine_rpm is not None:
        sample["engine_rpm"] = engine_rpm
    if dominant_freq_hz is not None:
        sample["dominant_freq_hz"] = dominant_freq_hz
    if location:
        sample["location"] = location
    if strength_peak_amp_g is not None:
        sample["strength_peak_amp_g"] = strength_peak_amp_g
    return sample


def make_analysis_sample(**kwargs: Any) -> SensorFrame:
    """Build one typed diagnostics sample from the shared raw sample builder."""

    return sensor_frames_from_mappings([make_sample(**kwargs)])[0]
