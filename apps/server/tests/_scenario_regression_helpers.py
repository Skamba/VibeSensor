"""Shared helpers for report scenario regression tests."""

from __future__ import annotations

from typing import Any

from builders import make_sample as _base_make_sample
from builders import standard_metadata as _base_standard_metadata

from vibesensor.analysis_settings import wheel_hz_from_speed_kmh

_ORDER_SOURCES: set[str] = {"wheel/tire", "driveline", "engine"}


def max_order_source_conf(
    summary: dict[str, Any],
    sources: set[str] = _ORDER_SOURCES,
) -> float:
    """Return max confidence among non-reference order-tracking findings."""
    return max(
        (
            float(finding.get("confidence_0_to_1") or 0.0)
            for finding in summary.get("findings", [])
            if not str(finding.get("finding_id", "")).startswith("REF_")
            and str(finding.get("suspected_source") or "").strip().lower() in sources
        ),
        default=0.0,
    )


def make_sample(
    *,
    t_s: float,
    speed_kmh: float | None = None,
    accel_x_g: float = 0.01,
    accel_y_g: float = 0.01,
    accel_z_g: float = 0.10,
    vibration_strength_db: float = 15.0,
    strength_bucket: str | None = None,
    strength_floor_amp_g: float = 0.002,
    client_name: str = "Front Left Wheel",
    client_id: str = "sensor-001",
    location: str = "",
    top_peaks: list[dict[str, float]] | None = None,
    engine_rpm: float | None = None,
    dominant_freq_hz: float | None = None,
) -> dict[str, Any]:
    """Compatibility sample factory shared across scenario regression modules."""
    effective_speed = 0.0 if speed_kmh is None else speed_kmh
    sample = _base_make_sample(
        t_s=t_s,
        speed_kmh=effective_speed,
        accel_x_g=accel_x_g,
        accel_y_g=accel_y_g,
        accel_z_g=accel_z_g,
        vibration_strength_db=vibration_strength_db,
        strength_floor_amp_g=strength_floor_amp_g,
        client_name=client_name,
        client_id=client_id,
        location=location,
        top_peaks=top_peaks,
        engine_rpm=engine_rpm,
        dominant_freq_hz=dominant_freq_hz,
    )
    if strength_bucket is not None:
        sample["strength_bucket"] = strength_bucket
    return sample


def build_speed_sweep_samples(
    *,
    n: int = 40,
    speed_start_kmh: float = 30.0,
    speed_end_kmh: float = 120.0,
    dt: float = 1.0,
    tire_circumference_m: float = 2.036,
    client_name: str = "Front Left Wheel",
    peak_amp: float = 0.05,
    add_wheel_1x: bool = True,
    vib_db: float = 18.0,
) -> list[dict[str, Any]]:
    """Create samples with linearly increasing speed and optional wheel-1x peaks."""
    samples: list[dict[str, Any]] = []
    for idx in range(n):
        t = idx * dt
        speed = speed_start_kmh + (speed_end_kmh - speed_start_kmh) * (idx / max(1, n - 1))
        peaks = []
        if add_wheel_1x:
            wheel_hz = wheel_hz_from_speed_kmh(speed, tire_circumference_m)
            if wheel_hz and wheel_hz > 0:
                peaks.append({"hz": wheel_hz, "amp": peak_amp})
        peaks.append({"hz": 142.5, "amp": 0.003})
        samples.append(
            make_sample(
                t_s=t,
                speed_kmh=speed,
                vibration_strength_db=vib_db,
                client_name=client_name,
                top_peaks=peaks,
                strength_floor_amp_g=0.003,
            )
        )
    return samples


def build_phased_samples(
    phase_segments: list[tuple[int, float, float]],
    *,
    start_t_s: float = 0.0,
    dt_s: float = 1.0,
) -> list[dict[str, Any]]:
    """Build samples from phase segments expressed as ``(count, start, end)``."""
    samples: list[dict[str, Any]] = []
    t_s = start_t_s
    for count, speed_start, speed_end in phase_segments:
        if count <= 0:
            continue
        for idx in range(count):
            if count == 1:
                speed_kmh = float(speed_end)
            else:
                ratio = idx / (count - 1)
                speed_kmh = float(speed_start + ((speed_end - speed_start) * ratio))
            samples.append(make_sample(t_s=t_s, speed_kmh=speed_kmh))
            t_s += dt_s
    return samples


def standard_metadata(
    *,
    tire_circumference_m: float = 2.036,
    raw_sample_rate_hz: float = 1000.0,
    final_drive_ratio: float = 3.08,
    current_gear_ratio: float = 0.64,
) -> dict[str, Any]:
    """Canonical metadata defaults for report scenario regression tests."""
    return _base_standard_metadata(
        tire_circumference_m=tire_circumference_m,
        raw_sample_rate_hz=raw_sample_rate_hz,
        final_drive_ratio=final_drive_ratio,
        current_gear_ratio=current_gear_ratio,
        sensor_model="adxl345",
        units={"accel_x_g": "g"},
    )
