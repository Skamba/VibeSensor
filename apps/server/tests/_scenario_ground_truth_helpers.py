"""Shared scenario builders and assertions for integration ground-truth tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from builders import make_sample as _make_sample
from builders import standard_metadata as _standard_metadata
from builders import wheel_hz as wheel_hz

from vibesensor.analysis import summarize_run_data

ALL_SENSORS = ["front-left", "front-right", "rear-left", "rear-right"]


def sensor_offset(sensor: str, modulo: int) -> int:
    """Stable per-sensor offset independent of PYTHONHASHSEED."""
    if sensor in ALL_SENSORS:
        return ALL_SENSORS.index(sensor) % modulo
    return sum(ord(char) for char in sensor) % modulo


def idle_phase(
    *,
    duration_s: float,
    sensors: list[str],
    start_t_s: float = 0.0,
    dt_s: float = 1.0,
    noise_amp: float = 0.003,
) -> list[dict[str, Any]]:
    """Generate idle/stationary samples with only noise peaks."""
    samples: list[dict[str, Any]] = []
    n = max(1, int(duration_s / dt_s))
    for idx in range(n):
        t = start_t_s + idx * dt_s
        for sensor in sensors:
            peaks = [
                {"hz": 12.5 + sensor_offset(sensor, 10), "amp": noise_amp},
                {"hz": 25.0, "amp": noise_amp * 0.5},
            ]
            samples.append(
                _make_sample(
                    t_s=t,
                    speed_kmh=0.0,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=6.0,
                    strength_floor_amp_g=noise_amp,
                )
            )
    return samples


def road_noise_phase(
    *,
    speed_kmh: float,
    duration_s: float,
    sensors: list[str],
    start_t_s: float = 0.0,
    dt_s: float = 1.0,
    noise_amp: float = 0.004,
    road_vib_db: float = 10.0,
) -> list[dict[str, Any]]:
    """Generate road-noise-only samples with no order peaks."""
    samples: list[dict[str, Any]] = []
    n = max(1, int(duration_s / dt_s))
    for idx in range(n):
        t = start_t_s + idx * dt_s
        for sensor in sensors:
            peaks = [
                {"hz": 15.0 + sensor_offset(sensor, 20), "amp": noise_amp},
                {"hz": 34.0, "amp": noise_amp * 0.7},
                {"hz": 88.0, "amp": noise_amp * 0.5},
            ]
            samples.append(
                _make_sample(
                    t_s=t,
                    speed_kmh=speed_kmh,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=road_vib_db,
                    strength_floor_amp_g=noise_amp,
                )
            )
    return samples


def ramp_phase(
    *,
    speed_start: float,
    speed_end: float,
    n_steps: int,
    step_duration_s: float,
    sensors: list[str],
    start_t_s: float = 0.0,
    dt_s: float = 1.0,
    noise_amp: float = 0.004,
    road_vib_db: float = 10.0,
) -> list[dict[str, Any]]:
    """Generate speed ramp phase with road-only noise."""
    samples: list[dict[str, Any]] = []
    t = start_t_s
    for step in range(n_steps):
        ratio = step / max(1, n_steps - 1)
        speed = speed_start + (speed_end - speed_start) * ratio
        n_per_step = max(1, int(step_duration_s / dt_s))
        for _ in range(n_per_step):
            for sensor in sensors:
                peaks = [
                    {"hz": 15.0 + sensor_offset(sensor, 20), "amp": noise_amp},
                    {"hz": 60.0, "amp": noise_amp * 0.6},
                ]
                samples.append(
                    _make_sample(
                        t_s=t,
                        speed_kmh=speed,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=road_vib_db,
                        strength_floor_amp_g=noise_amp,
                    )
                )
            t += dt_s
    return samples


def fault_phase(
    *,
    speed_kmh: float,
    duration_s: float,
    fault_sensor: str,
    sensors: list[str],
    start_t_s: float = 0.0,
    dt_s: float = 1.0,
    fault_amp: float = 0.06,
    noise_amp: float = 0.004,
    fault_vib_db: float = 26.0,
    noise_vib_db: float = 8.0,
    add_wheel_2x: bool = True,
    transfer_fraction: float = 0.20,
) -> list[dict[str, Any]]:
    """Generate constant-speed wheel-fault samples with one dominant sensor."""
    samples: list[dict[str, Any]] = []
    whz = wheel_hz(speed_kmh)
    n = max(1, int(duration_s / dt_s))
    for idx in range(n):
        t = start_t_s + idx * dt_s
        for sensor in sensors:
            if sensor == fault_sensor:
                peaks = [{"hz": whz, "amp": fault_amp}]
                if add_wheel_2x:
                    peaks.append({"hz": whz * 2, "amp": fault_amp * 0.4})
                peaks.append({"hz": 142.5, "amp": noise_amp})
                samples.append(
                    _make_sample(
                        t_s=t,
                        speed_kmh=speed_kmh,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=fault_vib_db,
                        strength_floor_amp_g=noise_amp,
                    )
                )
                continue

            peaks = [{"hz": 142.5, "amp": noise_amp}, {"hz": 87.3, "amp": noise_amp * 0.8}]
            if transfer_fraction > 0:
                peaks.insert(0, {"hz": whz, "amp": fault_amp * transfer_fraction})
                if add_wheel_2x:
                    peaks.insert(1, {"hz": whz * 2, "amp": fault_amp * transfer_fraction * 0.24})
            samples.append(
                _make_sample(
                    t_s=t,
                    speed_kmh=speed_kmh,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=noise_vib_db,
                    strength_floor_amp_g=noise_amp,
                )
            )
    return samples


def scenario_metadata(*, language: str = "en") -> dict[str, Any]:
    """Return shared ground-truth scenario metadata."""
    return _standard_metadata(language=language)


def get_top_cause(summary: dict[str, Any]) -> dict[str, Any]:
    """Return the highest-priority top cause from a summary."""
    top_causes = summary.get("top_causes", [])
    assert top_causes, "No top causes found in summary"
    return top_causes[0]


@dataclass(frozen=True)
class PhaseStep:
    """Explicit scenario phase step used to build scenario summaries."""

    builder: Callable[..., list[dict[str, Any]]]
    duration_s: float
    kwargs: dict[str, Any]


@dataclass(frozen=True)
class ScenarioSpec:
    """Scenario definition and expected contract for one ground-truth case."""

    case_id: str
    language: str
    file_name: str
    phases: tuple[PhaseStep, ...]
    expected_source: str
    expected_location: str
    expected_speed_band_range: tuple[float, float]
    confidence_range: tuple[float, float]
    expect_no_weak_spatial: bool = False
    expect_wheel_signatures: bool = True
    expect_not_engine: bool = True


def build_summary_from_scenario(spec: ScenarioSpec) -> dict[str, Any]:
    """Build a summary for one explicit scenario specification."""
    samples: list[dict[str, Any]] = []
    t = 0.0
    for step in spec.phases:
        samples.extend(step.builder(start_t_s=t, sensors=ALL_SENSORS, **step.kwargs))
        t += step.duration_s
    return summarize_run_data(
        scenario_metadata(language=spec.language),
        samples,
        lang=spec.language,
        file_name=spec.file_name,
    )
