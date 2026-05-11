"""Wheel-order fault sample builders."""

from __future__ import annotations

from typing import Any

from test_support.core import wheel_hz
from test_support.fault_scenario_types import (
    AdditionalFaultSpec,
    own_fault_peaks,
    resolve_fault_specs,
    transfer_peaks_for_sensor,
)
from test_support.sample_scenarios import make_sample


def make_fault_samples(
    *,
    fault_sensor: str,
    sensors: list[str],
    speed_kmh: float = 80.0,
    n_samples: int = 30,
    dt_s: float = 1.0,
    start_t_s: float = 0.0,
    fault_amp: float = 0.06,
    noise_amp: float = 0.004,
    fault_vib_db: float = 26.0,
    noise_vib_db: float = 8.0,
    add_wheel_2x: bool = True,
    add_wheel_3x: bool = False,
    transfer_fraction: float | None = None,
    additional_faults: list[AdditionalFaultSpec] | None = None,
    _wheel_hz_override: float | None = None,
) -> list[dict[str, Any]]:
    """Generate wheel-order fault samples with deterministic cross-sensor coupling."""
    samples: list[dict[str, Any]] = []
    whz = _wheel_hz_override if _wheel_hz_override is not None else wheel_hz(speed_kmh)
    fault_specs = resolve_fault_specs(
        fault_sensor=fault_sensor,
        fault_amp=fault_amp,
        fault_vib_db=fault_vib_db,
        add_wheel_2x=add_wheel_2x,
        add_wheel_3x=add_wheel_3x,
        additional_faults=additional_faults,
    )
    fault_specs_by_sensor = {fault.sensor: fault for fault in fault_specs}
    include_transfer_harmonics = len(fault_specs) == 1 and add_wheel_2x
    for i in range(n_samples):
        t = start_t_s + i * dt_s
        for sensor in sensors:
            own_fault = fault_specs_by_sensor.get(sensor)
            if own_fault is not None:
                peaks = own_fault_peaks(
                    fault=own_fault,
                    whz=whz,
                    noise_amp=noise_amp,
                )
                peaks.extend(
                    transfer_peaks_for_sensor(
                        current_sensor=sensor,
                        fault_specs=fault_specs,
                        whz=whz,
                        transfer_fraction=transfer_fraction,
                        include_harmonics=False,
                    )
                )
                samples.append(
                    make_sample(
                        t_s=t,
                        speed_kmh=speed_kmh,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=own_fault.vibration_strength_db,
                        strength_floor_amp_g=noise_amp,
                    ),
                )
            else:
                other_peaks = transfer_peaks_for_sensor(
                    current_sensor=sensor,
                    fault_specs=fault_specs,
                    whz=whz,
                    transfer_fraction=transfer_fraction,
                    include_harmonics=include_transfer_harmonics,
                )
                other_peaks.extend(
                    [
                        {"hz": 142.5, "amp": noise_amp},
                        {"hz": 87.3, "amp": noise_amp * 0.8},
                    ]
                )
                samples.append(
                    make_sample(
                        t_s=t,
                        speed_kmh=speed_kmh,
                        client_name=sensor,
                        top_peaks=other_peaks,
                        vibration_strength_db=noise_vib_db,
                        strength_floor_amp_g=noise_amp,
                    ),
                )
    return samples


def make_speed_sweep_fault_samples(
    *,
    fault_sensor: str,
    sensors: list[str],
    speed_start: float = 40.0,
    speed_end: float = 100.0,
    n_steps: int = 5,
    samples_per_step: int = 10,
    dt_s: float = 1.0,
    start_t_s: float = 0.0,
    fault_amp: float = 0.06,
    noise_amp: float = 0.004,
    fault_vib_db: float = 26.0,
    noise_vib_db: float = 8.0,
) -> list[dict[str, Any]]:
    """Generate fault samples across a sweep of speeds."""
    samples: list[dict[str, Any]] = []
    t = start_t_s
    for step in range(n_steps):
        ratio = step / max(1, n_steps - 1)
        speed = speed_start + (speed_end - speed_start) * ratio
        samples.extend(
            make_fault_samples(
                fault_sensor=fault_sensor,
                sensors=sensors,
                speed_kmh=speed,
                n_samples=samples_per_step,
                dt_s=dt_s,
                start_t_s=t,
                fault_amp=fault_amp,
                noise_amp=noise_amp,
                fault_vib_db=fault_vib_db,
                noise_vib_db=noise_vib_db,
            ),
        )
        t += samples_per_step * dt_s
    return samples


def build_fault_samples_at_speed(
    *,
    speed_kmh: float,
    fault_sensor: str,
    other_sensors: list[str],
    n_samples: int = 30,
    dt_s: float = 1.0,
    start_t_s: float = 0.0,
    fault_amp: float = 0.06,
    noise_amp: float = 0.004,
    fault_vib_db: float = 24.0,
    noise_vib_db: float = 8.0,
    add_wheel_2x: bool = True,
    transfer_fraction: float = 0.20,
) -> list[dict[str, Any]]:
    """Build fault samples at a fixed speed for one faulty sensor."""
    sensors = [fault_sensor, *other_sensors]
    return make_fault_samples(
        fault_sensor=fault_sensor,
        sensors=sensors,
        speed_kmh=speed_kmh,
        n_samples=n_samples,
        dt_s=dt_s,
        start_t_s=start_t_s,
        fault_amp=fault_amp,
        noise_amp=noise_amp,
        fault_vib_db=fault_vib_db,
        noise_vib_db=noise_vib_db,
        add_wheel_2x=add_wheel_2x,
        transfer_fraction=transfer_fraction,
    )


def build_speed_sweep_fault_samples(
    *,
    speed_start_kmh: float,
    speed_end_kmh: float,
    fault_sensor: str,
    other_sensors: list[str],
    n_samples: int = 40,
    dt_s: float = 1.0,
    start_t_s: float = 0.0,
    fault_amp: float = 0.06,
    noise_amp: float = 0.004,
    fault_vib_db: float = 24.0,
    noise_vib_db: float = 8.0,
    transfer_fraction: float = 0.20,
) -> list[dict[str, Any]]:
    """Build fault samples across a speed sweep."""
    sensors = [fault_sensor, *other_sensors]
    return make_speed_sweep_fault_samples(
        fault_sensor=fault_sensor,
        sensors=sensors,
        speed_start=speed_start_kmh,
        speed_end=speed_end_kmh,
        n_steps=n_samples,
        samples_per_step=1,
        dt_s=dt_s,
        start_t_s=start_t_s,
        fault_amp=fault_amp,
        noise_amp=noise_amp,
        fault_vib_db=fault_vib_db,
        noise_vib_db=noise_vib_db,
    )
