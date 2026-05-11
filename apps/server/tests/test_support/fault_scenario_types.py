"""Shared fault scenario DTOs and peak helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from test_support.core import _fault_transfer_fraction


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


def apply_gain_mismatch(
    base: list[dict[str, object]],
    *,
    fault_sensor: str,
    gain_factor: float,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for sample in base:
        if sample["client_name"] == fault_sensor:
            sample = {**sample}
            sample["top_peaks"] = [
                {"hz": peak["hz"], "amp": peak["amp"] * gain_factor}
                for peak in sample["top_peaks"]  # type: ignore[index]
            ]
            sample["vibration_strength_db"] = float(sample["vibration_strength_db"]) + 3.0
        result.append(sample)
    return result
