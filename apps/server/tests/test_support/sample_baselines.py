"""Baseline and road-surface sample scenario builders."""

from __future__ import annotations

from typing import Any

from test_support.core import _stable_hash
from test_support.sample_builders import make_sample


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
