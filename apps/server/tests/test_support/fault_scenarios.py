"""Fault-oriented synthetic scenario builders for tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

from test_support.core import (
    _fault_transfer_fraction,
    _stable_hash,
    engine_hz,
    profile_wheel_hz,
    wheel_hz,
)
from test_support.sample_scenarios import make_sample


class AdditionalFaultSpec(TypedDict):
    sensor: str
    amp: float
    vibration_strength_db: float


@dataclass(frozen=True, slots=True)
class _ResolvedFaultSpec:
    sensor: str
    amp: float
    vibration_strength_db: float
    wheel_2x_scale: float
    wheel_3x_scale: float | None
    background_hz: float


def _resolve_fault_specs(
    *,
    fault_sensor: str,
    fault_amp: float,
    fault_vib_db: float,
    add_wheel_2x: bool,
    add_wheel_3x: bool,
    additional_faults: list[AdditionalFaultSpec] | None,
) -> list[_ResolvedFaultSpec]:
    specs = [
        _ResolvedFaultSpec(
            sensor=fault_sensor,
            amp=fault_amp,
            vibration_strength_db=fault_vib_db,
            wheel_2x_scale=0.4 if add_wheel_2x else 0.0,
            wheel_3x_scale=0.2 if add_wheel_3x else None,
            background_hz=142.5,
        ),
    ]
    for fault in additional_faults or []:
        specs.append(
            _ResolvedFaultSpec(
                sensor=fault["sensor"],
                amp=fault["amp"],
                vibration_strength_db=fault["vibration_strength_db"],
                wheel_2x_scale=0.35 if add_wheel_2x else 0.0,
                wheel_3x_scale=None,
                background_hz=87.3,
            ),
        )
    return specs


def _transfer_peaks_for_sensor(
    *,
    current_sensor: str,
    fault_specs: list[_ResolvedFaultSpec],
    whz: float,
    transfer_fraction: float | None,
    include_harmonics: bool,
) -> list[dict[str, float]]:
    peaks: list[dict[str, float]] = []
    for fault in fault_specs:
        if fault.sensor == current_sensor:
            continue
        transfer = _fault_transfer_fraction(
            fault.sensor,
            current_sensor,
            override=transfer_fraction,
        )
        if transfer <= 0:
            continue
        peaks.append({"hz": whz, "amp": fault.amp * transfer})
        if include_harmonics and fault.wheel_2x_scale > 0.0:
            peaks.append({"hz": whz * 2, "amp": fault.amp * transfer * 0.24})
    return peaks


def _own_fault_peaks(
    *,
    fault: _ResolvedFaultSpec,
    whz: float,
    noise_amp: float,
) -> list[dict[str, float]]:
    peaks: list[dict[str, float]] = [{"hz": whz, "amp": fault.amp}]
    if fault.wheel_2x_scale > 0.0:
        peaks.append({"hz": whz * 2, "amp": fault.amp * fault.wheel_2x_scale})
    if fault.wheel_3x_scale is not None:
        peaks.append({"hz": whz * 3, "amp": fault.amp * fault.wheel_3x_scale})
    peaks.append({"hz": fault.background_hz, "amp": noise_amp})
    return peaks


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
    fault_specs = _resolve_fault_specs(
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
                peaks = _own_fault_peaks(
                    fault=own_fault,
                    whz=whz,
                    noise_amp=noise_amp,
                )
                peaks.extend(
                    _transfer_peaks_for_sensor(
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
                other_peaks = _transfer_peaks_for_sensor(
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
) -> list[dict[str, Any]]:
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
    result: list[dict[str, Any]] = []
    for sample in base:
        if sample["client_name"] == fault_sensor:
            sample = {**sample}
            sample["top_peaks"] = [
                {"hz": peak["hz"], "amp": peak["amp"] * gain_factor} for peak in sample["top_peaks"]
            ]
            sample["vibration_strength_db"] = sample["vibration_strength_db"] + 3.0
        result.append(sample)
    return result


def make_engine_order_samples(
    *,
    sensors: list[str],
    speed_kmh: float = 80.0,
    n_samples: int = 30,
    dt_s: float = 1.0,
    start_t_s: float = 0.0,
    engine_amp: float = 0.05,
    engine_vib_db: float = 24.0,
    noise_amp: float = 0.004,
    _engine_hz_override: float | None = None,
) -> list[dict[str, Any]]:
    """Generate engine-order harmonics on all sensors."""
    ehz = _engine_hz_override if _engine_hz_override is not None else engine_hz(speed_kmh)
    samples: list[dict[str, Any]] = []
    for i in range(n_samples):
        t = start_t_s + i * dt_s
        for sensor in sensors:
            jitter = (_stable_hash(sensor + str(i)) % 10) * 0.001
            peaks = [
                {"hz": ehz, "amp": engine_amp + jitter},
                {"hz": ehz * 2, "amp": (engine_amp + jitter) * 0.5},
                {"hz": ehz * 0.5, "amp": (engine_amp + jitter) * 0.3},
                {"hz": 200.0, "amp": noise_amp},
            ]
            samples.append(
                make_sample(
                    t_s=t,
                    speed_kmh=speed_kmh,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=engine_vib_db,
                    strength_floor_amp_g=noise_amp,
                    engine_rpm=ehz * 60.0,
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
) -> list[dict[str, Any]]:
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
    result: list[dict[str, Any]] = []
    for sample in base:
        if sample["client_name"] == fault_sensor:
            sample = {**sample}
            sample["top_peaks"] = [
                {"hz": peak["hz"], "amp": peak["amp"] * gain_factor} for peak in sample["top_peaks"]
            ]
            sample["vibration_strength_db"] = sample["vibration_strength_db"] + 3.0
        result.append(sample)
    return result


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
