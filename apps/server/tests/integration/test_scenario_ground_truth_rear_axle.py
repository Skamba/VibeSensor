"""Rear-axle and high-speed ground-truth scenario contracts."""

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
    road_noise_phase,
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
)

REAR_AXLE_SCENARIOS = [SCENARIO_02, SCENARIO_03]


@pytest.fixture(params=REAR_AXLE_SCENARIOS, ids=lambda spec: spec.case_id)
def scenario(request: pytest.FixtureRequest) -> ScenarioSpec:
    return request.param


@pytest.fixture
def summary(scenario: ScenarioSpec) -> dict:
    return build_summary_from_scenario(scenario)


def test_rear_axle_summary_sections(scenario: ScenarioSpec, summary: dict) -> None:
    assert_summary_sections(summary, expected_lang=scenario.language, min_top_causes=1)


def test_rear_axle_top_cause_contract(scenario: ScenarioSpec, summary: dict) -> None:
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
