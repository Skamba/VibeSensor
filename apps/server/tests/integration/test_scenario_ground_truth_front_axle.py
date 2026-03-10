"""Front-axle and onset-oriented ground-truth scenario contracts."""

from __future__ import annotations

import pytest
from test_support.core import assert_summary_sections, assert_top_cause_contract
from test_support.scenario_ground_truth import (
    PhaseStep,
    ScenarioSpec,
    build_summary_from_scenario,
    fault_phase,
    get_top_cause,
    idle_phase,
    ramp_phase,
    road_noise_phase,
)

SCENARIO_01 = ScenarioSpec(
    case_id="01_idle_to_100_fr_en",
    language="en",
    file_name="01_idle_to_100_fr_en",
    phases=(
        PhaseStep(idle_phase, 45.0, {"duration_s": 45.0}),
        PhaseStep(
            ramp_phase,
            20.0,
            {
                "speed_start": 20.0,
                "speed_end": 100.0,
                "n_steps": 5,
                "step_duration_s": 4.0,
            },
        ),
        PhaseStep(
            fault_phase,
            40.0,
            {
                "speed_kmh": 100.0,
                "duration_s": 40.0,
                "fault_sensor": "front-right",
            },
        ),
    ),
    expected_source="wheel",
    expected_location="front-right",
    expected_speed_band_range=(90.0, 110.0),
    confidence_range=(0.40, 0.85),
    expect_no_weak_spatial=True,
)

SCENARIO_04 = ScenarioSpec(
    case_id="04_coastdown_fl_nl",
    language="nl",
    file_name="04_coastdown_fl_nl",
    phases=(
        PhaseStep(
            road_noise_phase,
            20.0,
            {"speed_kmh": 110.0, "duration_s": 20.0, "road_vib_db": 12.0},
        ),
        PhaseStep(
            fault_phase,
            20.0,
            {
                "speed_kmh": 90.0,
                "duration_s": 20.0,
                "fault_sensor": "front-left",
                "fault_amp": 0.045,
                "fault_vib_db": 22.0,
            },
        ),
        PhaseStep(
            fault_phase,
            20.0,
            {
                "speed_kmh": 70.0,
                "duration_s": 20.0,
                "fault_sensor": "front-left",
                "fault_amp": 0.07,
                "fault_vib_db": 28.0,
            },
        ),
        PhaseStep(
            fault_phase,
            20.0,
            {
                "speed_kmh": 50.0,
                "duration_s": 20.0,
                "fault_sensor": "front-left",
                "fault_amp": 0.045,
                "fault_vib_db": 22.0,
            },
        ),
        PhaseStep(road_noise_phase, 20.0, {"speed_kmh": 30.0, "duration_s": 20.0}),
    ),
    expected_source="wheel",
    expected_location="front-left",
    expected_speed_band_range=(40.0, 100.0),
    confidence_range=(0.35, 0.85),
    expect_no_weak_spatial=True,
)

SCENARIO_05 = ScenarioSpec(
    case_id="05_noise_then_fl_en",
    language="en",
    file_name="05_noise_then_fl_en",
    phases=(
        PhaseStep(
            road_noise_phase,
            40.0,
            {
                "speed_kmh": 80.0,
                "duration_s": 40.0,
                "noise_amp": 0.005,
                "road_vib_db": 14.0,
            },
        ),
        PhaseStep(
            road_noise_phase,
            20.0,
            {
                "speed_kmh": 80.0,
                "duration_s": 20.0,
                "noise_amp": 0.008,
                "road_vib_db": 18.0,
            },
        ),
        PhaseStep(
            fault_phase,
            40.0,
            {
                "speed_kmh": 100.0,
                "duration_s": 40.0,
                "fault_sensor": "front-left",
            },
        ),
        PhaseStep(road_noise_phase, 15.0, {"speed_kmh": 60.0, "duration_s": 15.0}),
    ),
    expected_source="wheel",
    expected_location="front-left",
    expected_speed_band_range=(90.0, 110.0),
    confidence_range=(0.30, 0.85),
    expect_no_weak_spatial=True,
)

FRONT_AXLE_SCENARIOS = [SCENARIO_01, SCENARIO_04, SCENARIO_05]


@pytest.fixture(params=FRONT_AXLE_SCENARIOS, ids=lambda spec: spec.case_id)
def scenario(request: pytest.FixtureRequest) -> ScenarioSpec:
    return request.param


@pytest.fixture
def summary(scenario: ScenarioSpec) -> dict:
    return build_summary_from_scenario(scenario)


def test_front_axle_summary_sections(scenario: ScenarioSpec, summary: dict) -> None:
    assert_summary_sections(summary, expected_lang=scenario.language, min_top_causes=1)


def test_front_axle_top_cause_contract(scenario: ScenarioSpec, summary: dict) -> None:
    assert_top_cause_contract(
        get_top_cause(summary),
        expected_source=scenario.expected_source,
        expected_location=scenario.expected_location,
        expected_speed_band_range=scenario.expected_speed_band_range,
        confidence_range=scenario.confidence_range,
        expect_no_weak_spatial=scenario.expect_no_weak_spatial,
        expect_wheel_signatures=scenario.expect_wheel_signatures,
        expect_not_engine=scenario.expect_not_engine,
    )
