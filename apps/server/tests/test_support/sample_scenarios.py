"""Baseline sample and non-fault scenario builders for tests."""

from __future__ import annotations

from typing import Any

from vibesensor_core.strength_bands import bucket_for_strength

from .core import _stable_hash


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


def make_noise_samples(
    *,
    sensors: list[str],
    speed_kmh: float = 60.0,
    n_samples: int = 30,
    dt_s: float = 1.0,
    start_t_s: float = 0.0,
    noise_amp: float = 0.004,
    vib_db: float = 10.0,
) -> list[dict[str, Any]]:
    """Generate broadband road-noise baseline on all *sensors*."""
    samples: list[dict[str, Any]] = []
    for i in range(n_samples):
        t = start_t_s + i * dt_s
        for sensor in sensors:
            offset = _stable_hash(sensor) % 20
            peaks = [
                {"hz": 15.0 + offset, "amp": noise_amp},
                {"hz": 34.0, "amp": noise_amp * 0.7},
                {"hz": 88.0, "amp": noise_amp * 0.5},
            ]
            samples.append(
                make_sample(
                    t_s=t,
                    speed_kmh=speed_kmh,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=vib_db,
                    strength_floor_amp_g=noise_amp,
                ),
            )
    return samples


def make_transient_samples(
    *,
    sensor: str,
    speed_kmh: float = 60.0,
    n_samples: int = 3,
    dt_s: float = 1.0,
    start_t_s: float = 0.0,
    spike_amp: float = 0.15,
    spike_vib_db: float = 35.0,
    spike_freq_hz: float = 50.0,
) -> list[dict[str, Any]]:
    """Generate short transient spike/impact on one sensor."""
    samples: list[dict[str, Any]] = []
    for i in range(n_samples):
        t = start_t_s + i * dt_s
        peaks = [
            {"hz": spike_freq_hz, "amp": spike_amp},
            {"hz": spike_freq_hz * 2.3, "amp": spike_amp * 0.6},
        ]
        samples.append(
            make_sample(
                t_s=t,
                speed_kmh=speed_kmh,
                client_name=sensor,
                top_peaks=peaks,
                vibration_strength_db=spike_vib_db,
                strength_floor_amp_g=0.003,
            ),
        )
    return samples


def make_diffuse_samples(
    *,
    sensors: list[str],
    speed_kmh: float = 80.0,
    n_samples: int = 30,
    dt_s: float = 1.0,
    start_t_s: float = 0.0,
    amp: float = 0.03,
    vib_db: float = 20.0,
    freq_hz: float = 25.0,
) -> list[dict[str, Any]]:
    """Generate uniform cross-sensor excitation (diffuse vibration)."""
    samples: list[dict[str, Any]] = []
    for i in range(n_samples):
        t = start_t_s + i * dt_s
        for sensor in sensors:
            jitter = (_stable_hash(sensor + str(i)) % 10) * 0.001
            peaks = [
                {"hz": freq_hz, "amp": amp + jitter},
                {"hz": freq_hz * 2.0, "amp": (amp + jitter) * 0.3},
            ]
            samples.append(
                make_sample(
                    t_s=t,
                    speed_kmh=speed_kmh,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=vib_db,
                    strength_floor_amp_g=0.003,
                ),
            )
    return samples


def make_idle_samples(
    *,
    sensors: list[str],
    n_samples: int = 10,
    dt_s: float = 1.0,
    start_t_s: float = 0.0,
    noise_amp: float = 0.003,
) -> list[dict[str, Any]]:
    """Generate stationary/idle samples (speed=0, low noise)."""
    samples: list[dict[str, Any]] = []
    for i in range(n_samples):
        t = start_t_s + i * dt_s
        for sensor in sensors:
            peaks = [
                {"hz": 12.5 + (_stable_hash(sensor) % 10), "amp": noise_amp},
                {"hz": 25.0, "amp": noise_amp * 0.5},
            ]
            samples.append(
                make_sample(
                    t_s=t,
                    speed_kmh=0.0,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=6.0,
                    strength_floor_amp_g=noise_amp,
                ),
            )
    return samples


def make_ramp_samples(
    *,
    sensors: list[str],
    speed_start: float = 20.0,
    speed_end: float = 100.0,
    n_samples: int = 20,
    dt_s: float = 1.0,
    start_t_s: float = 0.0,
    noise_amp: float = 0.004,
    vib_db: float = 10.0,
) -> list[dict[str, Any]]:
    """Generate speed ramp (acceleration or deceleration)."""
    samples: list[dict[str, Any]] = []
    for i in range(n_samples):
        t = start_t_s + i * dt_s
        ratio = i / max(1, n_samples - 1)
        speed = speed_start + (speed_end - speed_start) * ratio
        for sensor in sensors:
            peaks = [
                {"hz": 15.0 + (_stable_hash(sensor) % 20), "amp": noise_amp},
                {"hz": 60.0, "amp": noise_amp * 0.6},
            ]
            samples.append(
                make_sample(
                    t_s=t,
                    speed_kmh=speed,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=vib_db,
                    strength_floor_amp_g=noise_amp,
                ),
            )
    return samples


def make_road_phase_samples(
    *,
    sensors: list[str],
    speed_kmh: float = 80.0,
    smooth_n: int = 15,
    rough_n: int = 10,
    pothole_n: int = 3,
    dt_s: float = 1.0,
    start_t_s: float = 0.0,
    smooth_amp: float = 0.003,
    rough_amp: float = 0.02,
    pothole_amp: float = 0.15,
) -> list[dict[str, Any]]:
    """Generate samples with road surface phase changes."""
    samples: list[dict[str, Any]] = []
    t = start_t_s

    for _i in range(smooth_n):
        for sensor in sensors:
            peaks = [
                {"hz": 20.0 + (_stable_hash(sensor) % 10), "amp": smooth_amp},
                {"hz": 50.0, "amp": smooth_amp * 0.5},
            ]
            samples.append(
                make_sample(
                    t_s=t,
                    speed_kmh=speed_kmh,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=8.0,
                    strength_floor_amp_g=smooth_amp,
                ),
            )
        t += dt_s

    for i in range(rough_n):
        for sensor in sensors:
            jitter = (_stable_hash(sensor + str(i)) % 10) * 0.002
            peaks = [
                {"hz": 30.0, "amp": rough_amp + jitter},
                {"hz": 60.0, "amp": (rough_amp + jitter) * 0.7},
                {"hz": 90.0, "amp": (rough_amp + jitter) * 0.4},
            ]
            samples.append(
                make_sample(
                    t_s=t,
                    speed_kmh=speed_kmh,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=18.0,
                    strength_floor_amp_g=rough_amp,
                ),
            )
        t += dt_s

    for _i in range(pothole_n):
        for sensor in sensors:
            peaks = [
                {"hz": 15.0, "amp": pothole_amp},
                {"hz": 40.0, "amp": pothole_amp * 0.8},
                {"hz": 80.0, "amp": pothole_amp * 0.4},
            ]
            samples.append(
                make_sample(
                    t_s=t,
                    speed_kmh=speed_kmh,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=35.0,
                    strength_floor_amp_g=0.003,
                ),
            )
        t += dt_s

    return samples
