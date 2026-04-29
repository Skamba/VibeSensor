"""Shared scenario builders and assertions for integration ground-truth tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from test_support.core import standard_metadata
from test_support.fault_scenarios import make_fault_samples
from test_support.sample_scenarios import (
    make_idle_samples,
    make_noise_samples,
    make_ramp_samples,
    make_road_phase_samples,
    make_speed_jitter_samples,
)
from vibesensor.adapters.analysis_summary import summarize_sensor_frames
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings

ALL_SENSORS = ["front-left", "front-right", "rear-left", "rear-right"]


def _sample_count(duration_s: float, dt_s: float) -> int:
    return max(1, int(duration_s / dt_s))


def idle_phase(
    *,
    duration_s: float,
    sensors: list[str],
    start_t_s: float = 0.0,
    dt_s: float = 1.0,
    noise_amp: float = 0.003,
) -> list[dict[str, Any]]:
    """Generate idle/stationary samples with only noise peaks."""
    return make_idle_samples(
        sensors=sensors,
        n_samples=_sample_count(duration_s, dt_s),
        dt_s=dt_s,
        start_t_s=start_t_s,
        noise_amp=noise_amp,
    )


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
    return make_noise_samples(
        sensors=sensors,
        speed_kmh=speed_kmh,
        n_samples=_sample_count(duration_s, dt_s),
        dt_s=dt_s,
        start_t_s=start_t_s,
        noise_amp=noise_amp,
        vib_db=road_vib_db,
    )


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
    total_samples = n_steps * _sample_count(step_duration_s, dt_s)
    return make_ramp_samples(
        sensors=sensors,
        speed_start=speed_start,
        speed_end=speed_end,
        n_samples=total_samples,
        dt_s=dt_s,
        start_t_s=start_t_s,
        noise_amp=noise_amp,
        vib_db=road_vib_db,
    )


def road_surface_phase(
    *,
    speed_kmh: float,
    smooth_n: int,
    rough_n: int,
    pothole_n: int,
    sensors: list[str],
    start_t_s: float = 0.0,
    rough_amp: float = 0.02,
    pothole_amp: float = 0.15,
) -> list[dict[str, Any]]:
    """Generate a mixed road-surface nuisance phase with pothole transients."""
    return make_road_phase_samples(
        sensors=sensors,
        speed_kmh=speed_kmh,
        smooth_n=smooth_n,
        rough_n=rough_n,
        pothole_n=pothole_n,
        start_t_s=start_t_s,
        rough_amp=rough_amp,
        pothole_amp=pothole_amp,
    )


def jitter_noise_phase(
    *,
    base_speed_kmh: float,
    duration_s: float,
    sensors: list[str],
    start_t_s: float = 0.0,
    jitter_amplitude: float = 8.0,
    noise_amp: float = 0.004,
    vib_db: float = 10.0,
) -> list[dict[str, Any]]:
    """Generate fluctuating-speed nuisance samples with no wheel fault present."""
    return make_speed_jitter_samples(
        sensors=sensors,
        base_speed_kmh=base_speed_kmh,
        jitter_amplitude=jitter_amplitude,
        n_samples=max(1, int(duration_s)),
        start_t_s=start_t_s,
        noise_amp=noise_amp,
        vib_db=vib_db,
    )


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
    return make_fault_samples(
        fault_sensor=fault_sensor,
        sensors=sensors,
        speed_kmh=speed_kmh,
        n_samples=_sample_count(duration_s, dt_s),
        dt_s=dt_s,
        start_t_s=start_t_s,
        fault_amp=fault_amp,
        noise_amp=noise_amp,
        fault_vib_db=fault_vib_db,
        noise_vib_db=noise_vib_db,
        add_wheel_2x=add_wheel_2x,
        transfer_fraction=transfer_fraction,
    )


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
    expected_source: str | None = None
    expected_location: str | None = None
    expected_speed_band_range: tuple[float, float] | None = None
    confidence_range: tuple[float, float] = (0.0, 1.0)
    expect_no_weak_spatial: bool = False
    expect_wheel_signatures: bool = True
    expect_not_engine: bool = True
    scenario_group: Literal["front_axle", "rear_axle", "nuisance"] = "front_axle"
    assert_mode: Literal["top_cause", "strict_no_fault", "tolerant_no_fault"] = "top_cause"


def build_summary_from_phases(
    *,
    language: str,
    file_name: str,
    phases: tuple[PhaseStep, ...],
) -> dict[str, Any]:
    """Build a summary for an explicit scenario phase sequence."""
    samples: list[dict[str, Any]] = []
    t = 0.0
    for step in phases:
        samples.extend(step.builder(start_t_s=t, sensors=ALL_SENSORS, **step.kwargs))
        t += step.duration_s
    return summarize_sensor_frames(
        run_metadata_from_mapping(standard_metadata(language=language)),
        sensor_frames_from_mappings(samples),
        lang=language,
        file_name=file_name,
    )


def build_summary_from_scenario(spec: ScenarioSpec) -> dict[str, Any]:
    """Build a summary for one explicit scenario specification."""
    return build_summary_from_phases(
        language=spec.language,
        file_name=spec.file_name,
        phases=spec.phases,
    )
