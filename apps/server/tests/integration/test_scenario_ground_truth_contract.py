"""Merged ground-truth scenario contracts for axle faults and nuisance baselines."""

from __future__ import annotations

import pytest
from test_support.assertions import assert_strict_no_fault, assert_tolerant_no_fault
from test_support.core import assert_summary_sections, assert_top_cause_contract
from test_support.scenario_ground_truth import (
    PhaseStep,
    ScenarioSpec,
    build_summary_from_scenario,
    fault_phase,
    get_top_cause,
    idle_phase,
    jitter_noise_phase,
    ramp_phase,
    road_noise_phase,
    road_surface_phase,
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
    scenario_group="front_axle",
)

SCENARIO_02 = ScenarioSpec(
    case_id="02_stop_go_rl_nl",
    language="nl",
    file_name="02_stop_go_rl_nl",
    phases=(
        PhaseStep(idle_phase, 20.0, {"duration_s": 20.0}),
        PhaseStep(road_noise_phase, 20.0, {"speed_kmh": 30.0, "duration_s": 20.0}),
        PhaseStep(
            fault_phase,
            20.0,
            {
                "speed_kmh": 50.0,
                "duration_s": 20.0,
                "fault_sensor": "rear-left",
            },
        ),
        PhaseStep(road_noise_phase, 15.0, {"speed_kmh": 10.0, "duration_s": 15.0}),
        PhaseStep(
            fault_phase,
            25.0,
            {
                "speed_kmh": 60.0,
                "duration_s": 25.0,
                "fault_sensor": "rear-left",
            },
        ),
    ),
    expected_source="wheel",
    expected_location="rear-left",
    expected_speed_band_range=(40.0, 70.0),
    confidence_range=(0.30, 0.80),
    scenario_group="rear_axle",
)

SCENARIO_03 = ScenarioSpec(
    case_id="03_high_speed_rr_en",
    language="en",
    file_name="03_high_speed_rr_en",
    phases=(
        PhaseStep(road_noise_phase, 20.0, {"speed_kmh": 60.0, "duration_s": 20.0}),
        PhaseStep(road_noise_phase, 20.0, {"speed_kmh": 90.0, "duration_s": 20.0}),
        PhaseStep(
            fault_phase,
            40.0,
            {
                "speed_kmh": 120.0,
                "duration_s": 40.0,
                "fault_sensor": "rear-right",
            },
        ),
        PhaseStep(road_noise_phase, 20.0, {"speed_kmh": 100.0, "duration_s": 20.0}),
    ),
    expected_source="wheel",
    expected_location="rear-right",
    expected_speed_band_range=(110.0, 130.0),
    confidence_range=(0.40, 0.85),
    expect_no_weak_spatial=True,
    scenario_group="rear_axle",
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
    scenario_group="front_axle",
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
    scenario_group="front_axle",
)

SCENARIO_06 = ScenarioSpec(
    case_id="06_intermittent_fl_en",
    language="en",
    file_name="06_intermittent_fl_en",
    phases=(
        PhaseStep(idle_phase, 15.0, {"duration_s": 15.0}),
        PhaseStep(
            road_noise_phase,
            15.0,
            {"speed_kmh": 60.0, "duration_s": 15.0, "road_vib_db": 12.0},
        ),
        PhaseStep(
            fault_phase,
            8.0,
            {
                "speed_kmh": 80.0,
                "duration_s": 8.0,
                "fault_sensor": "front-left",
                "fault_amp": 0.05,
                "fault_vib_db": 22.0,
                "noise_amp": 0.005,
                "noise_vib_db": 10.0,
            },
        ),
        PhaseStep(
            road_noise_phase,
            10.0,
            {
                "speed_kmh": 80.0,
                "duration_s": 10.0,
                "noise_amp": 0.005,
                "road_vib_db": 13.0,
            },
        ),
        PhaseStep(
            fault_phase,
            24.0,
            {
                "speed_kmh": 80.0,
                "duration_s": 24.0,
                "fault_sensor": "front-left",
                "fault_amp": 0.065,
                "fault_vib_db": 27.0,
                "noise_amp": 0.005,
                "noise_vib_db": 10.0,
            },
        ),
        PhaseStep(
            road_noise_phase,
            12.0,
            {"speed_kmh": 60.0, "duration_s": 12.0, "road_vib_db": 11.0},
        ),
    ),
    expected_source="wheel",
    expected_location="front-left",
    expected_speed_band_range=(70.0, 90.0),
    confidence_range=(0.25, 0.80),
    scenario_group="front_axle",
)

SCENARIO_07 = ScenarioSpec(
    case_id="07_midspeed_rr_noise_en",
    language="en",
    file_name="07_midspeed_rr_noise_en",
    phases=(
        PhaseStep(
            road_noise_phase,
            20.0,
            {
                "speed_kmh": 70.0,
                "duration_s": 20.0,
                "noise_amp": 0.006,
                "road_vib_db": 14.0,
            },
        ),
        PhaseStep(
            fault_phase,
            30.0,
            {
                "speed_kmh": 80.0,
                "duration_s": 30.0,
                "fault_sensor": "rear-right",
                "fault_amp": 0.05,
                "fault_vib_db": 22.0,
                "noise_amp": 0.006,
                "noise_vib_db": 14.0,
            },
        ),
        PhaseStep(
            road_noise_phase,
            15.0,
            {
                "speed_kmh": 80.0,
                "duration_s": 15.0,
                "noise_amp": 0.006,
                "road_vib_db": 15.0,
            },
        ),
        PhaseStep(
            fault_phase,
            25.0,
            {
                "speed_kmh": 90.0,
                "duration_s": 25.0,
                "fault_sensor": "rear-right",
                "fault_amp": 0.06,
                "fault_vib_db": 24.0,
                "noise_amp": 0.006,
                "noise_vib_db": 14.0,
            },
        ),
    ),
    expected_source="wheel",
    expected_location="rear-right",
    expected_speed_band_range=(70.0, 95.0),
    confidence_range=(0.25, 0.80),
    scenario_group="rear_axle",
)

SCENARIO_08 = ScenarioSpec(
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
    scenario_group="nuisance",
    assert_mode="tolerant_no_fault",
)

SCENARIO_09 = ScenarioSpec(
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
    scenario_group="nuisance",
    assert_mode="tolerant_no_fault",
)

SCENARIO_10 = ScenarioSpec(
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
    scenario_group="nuisance",
    assert_mode="strict_no_fault",
)

GROUND_TRUTH_SCENARIOS = [
    SCENARIO_01,
    SCENARIO_02,
    SCENARIO_03,
    SCENARIO_04,
    SCENARIO_05,
    SCENARIO_06,
    SCENARIO_07,
    SCENARIO_08,
    SCENARIO_09,
    SCENARIO_10,
]


def test_ground_truth_scenario_ids_are_unique() -> None:
    case_ids = [scenario.case_id for scenario in GROUND_TRUTH_SCENARIOS]
    assert len(case_ids) == len(set(case_ids))


@pytest.fixture(params=GROUND_TRUTH_SCENARIOS, ids=lambda spec: spec.case_id)
def scenario(request: pytest.FixtureRequest) -> ScenarioSpec:
    return request.param


@pytest.fixture
def summary(scenario: ScenarioSpec) -> dict[str, object]:
    return build_summary_from_scenario(scenario)


def test_ground_truth_summary_sections(scenario: ScenarioSpec, summary: dict[str, object]) -> None:
    min_top_causes = 0 if scenario.assert_mode != "top_cause" else 1
    assert_summary_sections(summary, expected_lang=scenario.language, min_top_causes=min_top_causes)


def test_ground_truth_contract(scenario: ScenarioSpec, summary: dict[str, object]) -> None:
    if scenario.assert_mode == "strict_no_fault":
        assert_strict_no_fault(summary, msg=scenario.case_id)
        return
    if scenario.assert_mode == "tolerant_no_fault":
        assert_tolerant_no_fault(summary, msg=scenario.case_id)
        return
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
