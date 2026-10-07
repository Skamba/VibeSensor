"""Hand-built analysis rows for focused tests: one row per sensor and step, peaks placed by hand.

Only for edge cases the simulator benchmark cannot produce; diagnosis accuracy belongs
in ``tests/integration/test_diagnosis_accuracy_benchmark.py``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, TypedDict

import numpy as np

from test_support.core import _fault_transfer_fraction, _stable_hash, engine_hz, wheel_hz
from vibesensor.dsp.strength_bands import bucket_for_strength
from vibesensor.live.payload_types import AxisMetrics

# The live spectrum's bins: 2048-point FFT at 800 Hz, 5 to 200 Hz.
_AXIS_SPECTRUM_FREQ_HZ = np.fft.rfftfreq(2048, d=1.0 / 800.0)[13:513].astype(np.float32)


def sensor_mac_id(client_name: str) -> str:
    """A stable MAC-style client id (12 hex digits) for a synthetic sensor name.

    Real sensors are keyed by MAC, never by their name or mounting location, so
    synthetic samples keep the three distinct and joins on any of them are exercised.
    """
    return "02" + hashlib.sha1(client_name.encode("utf-8")).hexdigest()[:10]


def axis_spectrum(*tones: tuple[float, float]) -> AxisMetrics:
    """One axis's live spectrum: a faint flat floor with each ``(hz, amp_g)`` tone on its bin."""
    amp = np.full(_AXIS_SPECTRUM_FREQ_HZ.shape, 1e-4, dtype=np.float32)
    for hz, amp_g in tones:
        amp[int(np.argmin(np.abs(_AXIS_SPECTRUM_FREQ_HZ - hz)))] = amp_g
    return {"freq": _AXIS_SPECTRUM_FREQ_HZ, "amp": amp}


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
        "client_id": client_id or sensor_mac_id(client_name),
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


class AdditionalFaultSpec(TypedDict):
    sensor: str
    amp: float
    vibration_strength_db: float


@dataclass(frozen=True, slots=True)
class ResolvedFaultSpec:
    sensor: str
    amp: float
    vibration_strength_db: float
    wheel_2x_scale: float
    wheel_3x_scale: float | None
    background_hz: float


def resolve_fault_specs(
    *,
    fault_sensor: str,
    fault_amp: float,
    fault_vib_db: float,
    add_wheel_2x: bool,
    add_wheel_3x: bool,
    additional_faults: list[AdditionalFaultSpec] | None,
) -> list[ResolvedFaultSpec]:
    specs = [
        ResolvedFaultSpec(
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
            ResolvedFaultSpec(
                sensor=fault["sensor"],
                amp=fault["amp"],
                vibration_strength_db=fault["vibration_strength_db"],
                wheel_2x_scale=0.35 if add_wheel_2x else 0.0,
                wheel_3x_scale=None,
                background_hz=87.3,
            ),
        )
    return specs


def transfer_peaks_for_sensor(
    *,
    current_sensor: str,
    fault_specs: list[ResolvedFaultSpec],
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


def own_fault_peaks(
    *,
    fault: ResolvedFaultSpec,
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
