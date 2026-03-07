# ruff: noqa: E501
"""Perturbation and transport-noise scenario builders for tests."""

from __future__ import annotations

from typing import Any

from .core import _stable_hash
from .sample_scenarios import make_sample


def make_dropout_samples(
    *,
    base_samples: list[dict[str, Any]],
    dropout_sensor: str,
    dropout_start_t: float,
    dropout_end_t: float,
) -> list[dict[str, Any]]:
    """Simulate sensor dropout by removing samples from one sensor."""
    return [
        sample
        for sample in base_samples
        if not (
            sample["client_name"] == dropout_sensor
            and dropout_start_t <= sample["t_s"] < dropout_end_t
        )
    ]


def make_out_of_order_samples(
    *,
    base_samples: list[dict[str, Any]],
    swap_indices: list[tuple[int, int]] | None = None,
) -> list[dict[str, Any]]:
    """Return samples with deterministic timestamp-order inversions."""
    result = list(base_samples)
    if swap_indices is None:
        n = len(result)
        swap_indices = [(i, i + 1) for i in range(2, min(n - 1, 12), 4)]
    for first, second in swap_indices:
        if first < len(result) and second < len(result):
            result[first], result[second] = result[second], result[first]
    return result


def make_clock_skew_samples(
    *,
    base_samples: list[dict[str, Any]],
    skew_sensor: str,
    skew_offset_s: float = 0.3,
) -> list[dict[str, Any]]:
    """Apply a fixed clock offset to one sensor's timestamps."""
    result: list[dict[str, Any]] = []
    for sample in base_samples:
        if sample["client_name"] == skew_sensor:
            sample = {**sample, "t_s": sample["t_s"] + skew_offset_s}
        result.append(sample)
    return result


def make_speed_jitter_samples(
    *,
    sensors: list[str],
    base_speed_kmh: float = 80.0,
    jitter_amplitude: float = 8.0,
    n_samples: int = 30,
    dt_s: float = 1.0,
    start_t_s: float = 0.0,
    noise_amp: float = 0.004,
    vib_db: float = 10.0,
) -> list[dict[str, Any]]:
    """Generate samples with fluctuating speed readings."""
    samples: list[dict[str, Any]] = []
    for i in range(n_samples):
        t = start_t_s + i * dt_s
        jitter = jitter_amplitude * ((_stable_hash(f"jitter-{i}") % 200) / 100.0 - 1.0)
        speed = max(5.0, base_speed_kmh + jitter)
        for sensor in sensors:
            offset = _stable_hash(sensor) % 20
            peaks = [
                {"hz": 15.0 + offset, "amp": noise_amp},
                {"hz": 34.0, "amp": noise_amp * 0.7},
            ]
            samples.append(
                make_sample(
                    t_s=t,
                    speed_kmh=speed,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=vib_db,
                    strength_floor_amp_g=noise_amp,
                )
            )
    return samples


def make_clipped_samples(
    *,
    base_samples: list[dict[str, Any]],
    clip_sensor: str,
    clip_amp: float = 0.10,
) -> list[dict[str, Any]]:
    """Clip peak amplitudes on one sensor to simulate saturation."""
    result: list[dict[str, Any]] = []
    for sample in base_samples:
        if sample["client_name"] == clip_sensor:
            sample = {**sample}
            sample["top_peaks"] = [
                {"hz": peak["hz"], "amp": min(peak["amp"], clip_amp)}
                for peak in sample["top_peaks"]
            ]
        result.append(sample)
    return result
