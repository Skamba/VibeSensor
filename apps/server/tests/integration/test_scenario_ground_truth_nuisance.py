"""No-fault and nuisance-oriented ground-truth scenario contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pytest
from test_support import (
    assert_strict_no_fault,
    assert_summary_sections,
    assert_tolerant_no_fault,
    make_road_phase_samples,
    make_speed_jitter_samples,
)
from test_support.scenario_ground_truth import (
    PhaseStep,
    build_summary_from_phases,
    idle_phase,
    ramp_phase,
    road_noise_phase,
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


@dataclass(frozen=True)
class NoFaultScenarioSpec:
    case_id: str
    language: str
    file_name: str
    phases: tuple[PhaseStep, ...]
    assert_mode: Literal["strict", "tolerant"] = "tolerant"


SCENARIO_08 = NoFaultScenarioSpec(
    case_id="08_pothole_nuisance_en",
    language="en",
    file_name="08_pothole_nuisance_en",
    phases=(
        PhaseStep(
            road_surface_phase,
            28.0,
            {
                "speed_kmh": 80.0,
                "smooth_n": 12,
                "rough_n": 12,
                "pothole_n": 4,
                "rough_amp": 0.018,
                "pothole_amp": 0.12,
            },
        ),
        PhaseStep(
            road_noise_phase,
            12.0,
            {"speed_kmh": 60.0, "duration_s": 12.0, "noise_amp": 0.005, "road_vib_db": 12.0},
        ),
    ),
)

SCENARIO_09 = NoFaultScenarioSpec(
    case_id="09_speed_jitter_baseline_nl",
    language="nl",
    file_name="09_speed_jitter_baseline_nl",
    phases=(
        PhaseStep(idle_phase, 10.0, {"duration_s": 10.0}),
        PhaseStep(
            jitter_noise_phase,
            36.0,
            {
                "base_speed_kmh": 85.0,
                "duration_s": 36.0,
                "jitter_amplitude": 12.0,
                "noise_amp": 0.005,
                "vib_db": 12.0,
            },
        ),
        PhaseStep(
            road_noise_phase,
            12.0,
            {"speed_kmh": 70.0, "duration_s": 12.0, "noise_amp": 0.005, "road_vib_db": 12.0},
        ),
    ),
)

SCENARIO_10 = NoFaultScenarioSpec(
    case_id="10_coastdown_noise_only_en",
    language="en",
    file_name="10_coastdown_noise_only_en",
    phases=(
        PhaseStep(
            road_noise_phase,
            15.0,
            {"speed_kmh": 110.0, "duration_s": 15.0, "noise_amp": 0.005, "road_vib_db": 13.0},
        ),
        PhaseStep(
            ramp_phase,
            20.0,
            {
                "speed_start": 110.0,
                "speed_end": 40.0,
                "n_steps": 5,
                "step_duration_s": 4.0,
                "noise_amp": 0.005,
                "road_vib_db": 12.0,
            },
        ),
        PhaseStep(
            road_noise_phase,
            15.0,
            {"speed_kmh": 35.0, "duration_s": 15.0, "noise_amp": 0.0045, "road_vib_db": 10.0},
        ),
        PhaseStep(idle_phase, 10.0, {"duration_s": 10.0}),
    ),
    assert_mode="strict",
)

NUISANCE_SCENARIOS = [SCENARIO_08, SCENARIO_09, SCENARIO_10]


@pytest.fixture(params=NUISANCE_SCENARIOS, ids=lambda spec: spec.case_id)
def scenario(request: pytest.FixtureRequest) -> NoFaultScenarioSpec:
    return request.param


@pytest.fixture
def summary(scenario: NoFaultScenarioSpec) -> dict[str, Any]:
    return build_summary_from_phases(
        language=scenario.language,
        file_name=scenario.file_name,
        phases=scenario.phases,
    )


def test_nuisance_summary_sections(scenario: NoFaultScenarioSpec, summary: dict[str, Any]) -> None:
    assert_summary_sections(summary, expected_lang=scenario.language, min_top_causes=0)


def test_nuisance_no_fault_contract(scenario: NoFaultScenarioSpec, summary: dict[str, Any]) -> None:
    if scenario.assert_mode == "strict":
        assert_strict_no_fault(summary, msg=scenario.case_id)
        return
    assert_tolerant_no_fault(summary, msg=scenario.case_id)
