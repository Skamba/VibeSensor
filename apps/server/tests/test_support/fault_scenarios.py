"""Stable facade for fault-oriented synthetic scenario builders."""

from __future__ import annotations

from test_support.engine_fault_scenarios import make_engine_order_samples
from test_support.fault_scenario_types import AdditionalFaultSpec, apply_gain_mismatch
from test_support.profile_fault_scenarios import (
    make_profile_engine_order_samples,
    make_profile_fault_samples,
    make_profile_gain_mismatch_samples,
    make_profile_speed_sweep_fault_samples,
)
from test_support.wheel_fault_scenarios import (
    build_fault_samples_at_speed,
    build_speed_sweep_fault_samples,
    make_fault_samples,
    make_speed_sweep_fault_samples,
)


def make_gain_mismatch_samples(
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
    gain_factor: float = 1.5,
) -> list[dict[str, object]]:
    """Generate wheel-order fault samples with gain mismatch on the fault sensor."""
    base = make_fault_samples(
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


__all__ = [
    "AdditionalFaultSpec",
    "build_fault_samples_at_speed",
    "build_speed_sweep_fault_samples",
    "make_engine_order_samples",
    "make_fault_samples",
    "make_gain_mismatch_samples",
    "make_profile_engine_order_samples",
    "make_profile_fault_samples",
    "make_profile_gain_mismatch_samples",
    "make_profile_speed_sweep_fault_samples",
    "make_speed_sweep_fault_samples",
]
