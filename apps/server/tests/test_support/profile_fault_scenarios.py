"""Vehicle-profile-aware fault sample builders."""

from __future__ import annotations

from typing import Any

from test_support.core import profile_wheel_hz
from test_support.engine_fault_scenarios import make_engine_order_samples
from test_support.fault_scenario_types import AdditionalFaultSpec, apply_gain_mismatch
from test_support.wheel_fault_scenarios import make_fault_samples


def make_profile_fault_samples(
    *,
    profile: dict[str, Any],
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
    transfer_fraction: float | None = None,
    additional_faults: list[AdditionalFaultSpec] | None = None,
) -> list[dict[str, Any]]:
    """Generate wheel-order fault samples using a specific car profile."""
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
        additional_faults=additional_faults,
        _wheel_hz_override=profile_wheel_hz(profile, speed_kmh),
    )


def make_profile_engine_order_samples(
    *,
    profile: dict[str, Any],
    sensors: list[str],
    speed_kmh: float = 80.0,
    n_samples: int = 30,
    dt_s: float = 1.0,
    start_t_s: float = 0.0,
    engine_amp: float = 0.05,
    engine_vib_db: float = 24.0,
    noise_amp: float = 0.004,
) -> list[dict[str, Any]]:
    """Profile-aware version of :func:`make_engine_order_samples`."""
    whz = profile_wheel_hz(profile, speed_kmh)
    ehz = whz * profile["final_drive_ratio"] * profile["current_gear_ratio"]
    return make_engine_order_samples(
        sensors=sensors,
        speed_kmh=speed_kmh,
        n_samples=n_samples,
        dt_s=dt_s,
        start_t_s=start_t_s,
        engine_amp=engine_amp,
        engine_vib_db=engine_vib_db,
        noise_amp=noise_amp,
        _engine_hz_override=ehz,
    )


def make_profile_speed_sweep_fault_samples(
    *,
    profile: dict[str, Any],
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
    """Profile-aware version of :func:`make_speed_sweep_fault_samples`."""
    samples: list[dict[str, Any]] = []
    t = start_t_s
    for step in range(n_steps):
        ratio = step / max(1, n_steps - 1)
        speed = speed_start + (speed_end - speed_start) * ratio
        samples.extend(
            make_profile_fault_samples(
                profile=profile,
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


def make_profile_gain_mismatch_samples(
    *,
    profile: dict[str, Any],
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
    gain_factor: float = 1.5,
) -> list[dict[str, object]]:
    """Profile-aware version of :func:`make_gain_mismatch_samples`."""
    base = make_profile_fault_samples(
        profile=profile,
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
    )
    return apply_gain_mismatch(base, fault_sensor=fault_sensor, gain_factor=gain_factor)
