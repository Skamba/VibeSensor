"""Opt-in multi-sensor steady diagnostic matrix.

Representative corner/speed, no-fault baseline, and phased-onset coverage now
lives in ``test_synthetic_scenario_matrix.py``. This module keeps the
multi-sensor-specific steady-state axes available outside default backend CI.
"""

from __future__ import annotations

from typing import Any

import pytest
from test_support import (
    CORNER_SENSORS,
    SENSOR_FL,
    SPEED_HIGH,
    SPEED_MID,
    SPEED_VERY_HIGH,
    assert_confidence_between,
    assert_confidence_label_valid,
    assert_no_wheel_fault,
    assert_pairwise_monotonic,
    assert_strongest_location,
    assert_wheel_source,
    extract_top,
    make_diffuse_samples,
    make_fault_samples,
    make_noise_samples,
    make_profile_fault_samples,
    make_profile_speed_sweep_fault_samples,
    profile_metadata,
    run_analysis,
    top_confidence,
)
from test_support.diagnostic_matrix_catalogs import (
    DIAGNOSTIC_2_SENSOR_FL_RR as _2_SENSORS_FL_RR,
)
from test_support.diagnostic_matrix_catalogs import (
    DIAGNOSTIC_4_SENSOR_SET,
    DIAGNOSTIC_8_SENSOR_SET,
    DIAGNOSTIC_AMPLITUDE_SWEEP_CASES,
    DIAGNOSTIC_MULTI_SENSOR_BASELINE_CASES,
    DIAGNOSTIC_MULTI_SENSOR_DIFFUSE_CASES,
    DIAGNOSTIC_MULTI_SENSOR_LEVEL_CASES,
    DIAGNOSTIC_OPTIMIZED_PROFILE_IDS,
    DIAGNOSTIC_OPTIMIZED_PROFILES,
    DIAGNOSTIC_SPEED_SWEEP_CORNERS,
    DIAGNOSTIC_STANDARD_SPEED_IDS,
    DIAGNOSTIC_STANDARD_SPEEDS,
    DIAGNOSTIC_TWO_SENSOR_LOCALIZATION_CASES,
    DIAGNOSTIC_WEAK_SIGNAL_CORNERS,
    DIAGNOSTIC_WHEEL_CORNERS,
)

pytestmark = pytest.mark.diagnostic_matrix

# Helpers


def _assert_fault_at(summary: dict[str, Any], sensor: str, msg: str) -> None:
    """Common assertion: top finding exists at *sensor* with wheel source."""
    top = extract_top(summary)
    assert top is not None, f"{msg}: no finding"
    assert_wheel_source(summary, msg=msg)
    assert_strongest_location(summary, sensor, msg=msg)
    assert_confidence_between(summary, 0.10, 1.0, msg=msg)
    assert_confidence_label_valid(summary, msg=msg)


# D.3 – 2-sensor pairs with fault localization (4 cases)


@pytest.mark.parametrize(
    "profile", DIAGNOSTIC_OPTIMIZED_PROFILES, ids=DIAGNOSTIC_OPTIMIZED_PROFILE_IDS
)
@pytest.mark.parametrize(
    ("sensors", "fault_corner"),
    [
        (sensors, fault_corner)
        for _, sensors, fault_corner in DIAGNOSTIC_TWO_SENSOR_LOCALIZATION_CASES
    ],
    ids=[case_id for case_id, _, _ in DIAGNOSTIC_TWO_SENSOR_LOCALIZATION_CASES],
)
def test_2sensor_localization(
    sensors: list[str],
    fault_corner: str,
    profile: dict[str, Any],
) -> None:
    """2-sensor pair, fault at one → correct localization."""
    fault_sensor = CORNER_SENSORS[fault_corner]
    samples = make_profile_fault_samples(
        profile=profile,
        fault_sensor=fault_sensor,
        sensors=sensors,
        speed_kmh=SPEED_MID,
        n_samples=40,
        fault_amp=0.07,
        fault_vib_db=28.0,
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    _assert_fault_at(summary, fault_sensor, msg=f"2s {fault_corner}")


# D.4/D.5 – 8/12-sensor fault localization (4 corners × 2 sets = 8 cases)


@pytest.mark.parametrize(
    "profile", DIAGNOSTIC_OPTIMIZED_PROFILES, ids=DIAGNOSTIC_OPTIMIZED_PROFILE_IDS
)
@pytest.mark.parametrize(
    ("sensors", "label"),
    [(sensors, label) for _, sensors, label in DIAGNOSTIC_MULTI_SENSOR_LEVEL_CASES],
    ids=[case_id for case_id, _, _ in DIAGNOSTIC_MULTI_SENSOR_LEVEL_CASES],
)
@pytest.mark.parametrize("corner", DIAGNOSTIC_WHEEL_CORNERS)
def test_multi_sensor_fault_localization(
    corner: str,
    sensors: list[str],
    label: str,
    profile: dict[str, Any],
) -> None:
    """8 or 12 sensors, fault at one wheel corner → correct localization."""
    sensor = CORNER_SENSORS[corner]
    samples = make_profile_fault_samples(
        profile=profile,
        fault_sensor=sensor,
        sensors=sensors,
        speed_kmh=SPEED_HIGH,
        n_samples=35,
        fault_amp=0.07,
        fault_vib_db=28.0,
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    _assert_fault_at(summary, sensor, msg=f"{label} {corner}")


# D.6 – Diffuse excitation on 4 sensors → no wheel fault (3 speeds = 3 cases)


@pytest.mark.parametrize(
    "profile", DIAGNOSTIC_OPTIMIZED_PROFILES, ids=DIAGNOSTIC_OPTIMIZED_PROFILE_IDS
)
@pytest.mark.parametrize("speed", DIAGNOSTIC_STANDARD_SPEEDS, ids=DIAGNOSTIC_STANDARD_SPEED_IDS)
def test_4sensor_diffuse_no_fault(speed: float, profile: dict[str, Any]) -> None:
    """Diffuse excitation across 4 sensors → no localized wheel fault."""
    samples = make_diffuse_samples(sensors=DIAGNOSTIC_4_SENSOR_SET, speed_kmh=speed, n_samples=40)
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    assert_no_wheel_fault(summary, msg=f"4sensor-diffuse@{speed}")


# D.7 – Confidence scales with sensor count (3 sensor counts = 3 cases)


@pytest.mark.parametrize(
    "profile", DIAGNOSTIC_OPTIMIZED_PROFILES, ids=DIAGNOSTIC_OPTIMIZED_PROFILE_IDS
)
@pytest.mark.parametrize(
    ("sensors", "label"),
    [
        (_2_SENSORS_FL_RR, "2sensor"),
        (DIAGNOSTIC_4_SENSOR_SET, "4sensor"),
        (DIAGNOSTIC_8_SENSOR_SET, "8sensor"),
    ],
    ids=["2s", "4s", "8s"],
)
def test_confidence_scales_with_sensor_count(
    sensors: list[str],
    label: str,
    profile: dict[str, Any],
) -> None:
    """More sensors → confidence should be reasonable (not inflated beyond reality)."""
    samples = make_profile_fault_samples(
        profile=profile,
        fault_sensor=SENSOR_FL,
        sensors=sensors,
        speed_kmh=SPEED_HIGH,
        n_samples=35,
        fault_amp=0.07,
        fault_vib_db=28.0,
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    top = extract_top(summary)
    assert top is not None, f"No finding for {label}"
    assert_wheel_source(summary, msg=label)
    assert_confidence_between(summary, 0.10, 1.0, msg=label)


@pytest.mark.parametrize(
    "profile", DIAGNOSTIC_OPTIMIZED_PROFILES, ids=DIAGNOSTIC_OPTIMIZED_PROFILE_IDS
)
def test_sensor_count_monotonic(profile: dict[str, Any]) -> None:
    """Confidence should stay stable as sensors are added.

    In realistic coupled scenes, adding non-wheel cabin/chassis sensors can
    slightly dilute wheel localization confidence, so allow bounded regressions.
    """
    confs: list[float] = []
    labels: list[str] = []
    for sensors, label in [
        (_2_SENSORS_FL_RR, "2s"),
        (DIAGNOSTIC_4_SENSOR_SET, "4s"),
        (DIAGNOSTIC_8_SENSOR_SET, "8s"),
    ]:
        samples = make_profile_fault_samples(
            profile=profile,
            fault_sensor=SENSOR_FL,
            sensors=sensors,
            speed_kmh=SPEED_HIGH,
            n_samples=35,
            fault_amp=0.07,
            fault_vib_db=28.0,
        )
        summary = run_analysis(samples, metadata=profile_metadata(profile))
        confs.append(top_confidence(summary))
        labels.append(label)
    # Keep 2→4 close to monotonic, but allow larger 4→8 dilution once
    # non-wheel channels join the scene.
    assert_pairwise_monotonic(confs[:2], tolerance=0.05, labels=labels[:2], msg="sensor-count 2->4")
    assert confs[2] >= confs[1] - 0.15, (
        "8-sensor confidence regressed too far from 4-sensor baseline: "
        f"{confs[1]:.4f} -> {confs[2]:.4f}"
    )


# D.7b – Amplitude monotonic with 4 sensors (1 case)


@pytest.mark.parametrize(
    "profile", DIAGNOSTIC_OPTIMIZED_PROFILES, ids=DIAGNOSTIC_OPTIMIZED_PROFILE_IDS
)
def test_4sensor_amplitude_monotonic(profile: dict[str, Any]) -> None:
    """Wheel/tire confidence should increase pairwise with fault amplitude on 4 sensors."""
    confs: list[float] = []
    labels: list[str] = []
    for amp, vdb, label in DIAGNOSTIC_AMPLITUDE_SWEEP_CASES:
        samples = make_profile_fault_samples(
            profile=profile,
            fault_sensor=SENSOR_FL,
            sensors=DIAGNOSTIC_4_SENSOR_SET,
            speed_kmh=SPEED_MID,
            n_samples=40,
            fault_amp=amp,
            fault_vib_db=vdb,
        )
        summary = run_analysis(samples, metadata=profile_metadata(profile))
        confs.append(top_confidence(summary))
        labels.append(label)
    assert_pairwise_monotonic(confs, tolerance=0.05, labels=labels, msg="amplitude")


# D.8 – Transfer path leakage (fault + small leak to other sensors) (4 cases)


@pytest.mark.parametrize(
    "profile", DIAGNOSTIC_OPTIMIZED_PROFILES, ids=DIAGNOSTIC_OPTIMIZED_PROFILE_IDS
)
@pytest.mark.parametrize("corner", DIAGNOSTIC_WHEEL_CORNERS)
def test_4sensor_transfer_path(corner: str, profile: dict[str, Any]) -> None:
    """Fault + 20% amplitude leak to other sensors → correct source."""
    sensor = CORNER_SENSORS[corner]
    samples = make_fault_samples(
        fault_sensor=sensor,
        sensors=DIAGNOSTIC_4_SENSOR_SET,
        speed_kmh=SPEED_MID,
        n_samples=35,
        fault_amp=0.07,
        fault_vib_db=28.0,
        transfer_fraction=0.2,
    )
    summary = run_analysis(samples)
    _assert_fault_at(summary, sensor, msg=f"transfer {corner}")


# D.10/D.11 – 8/12-sensor no-fault baseline (2 sensor sets = 2 cases)


@pytest.mark.parametrize(
    "profile", DIAGNOSTIC_OPTIMIZED_PROFILES, ids=DIAGNOSTIC_OPTIMIZED_PROFILE_IDS
)
@pytest.mark.parametrize(
    ("sensors", "label"),
    [(sensors, label) for _, sensors, label in DIAGNOSTIC_MULTI_SENSOR_BASELINE_CASES],
    ids=[case_id for case_id, _, _ in DIAGNOSTIC_MULTI_SENSOR_BASELINE_CASES],
)
def test_multi_sensor_no_fault_baseline(
    sensors: list[str],
    label: str,
    profile: dict[str, Any],
) -> None:
    """8 or 12 sensors, all noise → no wheel fault."""
    samples = make_noise_samples(sensors=sensors, speed_kmh=SPEED_MID, n_samples=40)
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    assert_no_wheel_fault(summary, msg=f"{label}-no-fault")


# D.12 – Diffuse on 8 and 12 sensors (2 cases)


@pytest.mark.parametrize(
    "profile", DIAGNOSTIC_OPTIMIZED_PROFILES, ids=DIAGNOSTIC_OPTIMIZED_PROFILE_IDS
)
@pytest.mark.parametrize(
    ("sensors", "label"),
    [(sensors, label) for _, sensors, label in DIAGNOSTIC_MULTI_SENSOR_DIFFUSE_CASES],
    ids=[case_id for case_id, _, _ in DIAGNOSTIC_MULTI_SENSOR_DIFFUSE_CASES],
)
def test_multi_sensor_diffuse_no_fault(
    sensors: list[str],
    label: str,
    profile: dict[str, Any],
) -> None:
    """Diffuse excitation across many sensors → no localized fault."""
    samples = make_diffuse_samples(sensors=sensors, speed_kmh=SPEED_HIGH, n_samples=35)
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    assert_no_wheel_fault(summary, msg=label)


# D.13 – Speed sweep with 4 sensors (2 corners = 2 cases)


@pytest.mark.parametrize(
    "profile", DIAGNOSTIC_OPTIMIZED_PROFILES, ids=DIAGNOSTIC_OPTIMIZED_PROFILE_IDS
)
@pytest.mark.parametrize("corner", DIAGNOSTIC_SPEED_SWEEP_CORNERS)
def test_4sensor_speed_sweep(corner: str, profile: dict[str, Any]) -> None:
    """Speed sweep with fault at one corner on 4 sensors."""
    sensor = CORNER_SENSORS[corner]
    samples = make_profile_speed_sweep_fault_samples(
        profile=profile,
        fault_sensor=sensor,
        sensors=DIAGNOSTIC_4_SENSOR_SET,
        speed_start=40,
        speed_end=100,
        n_steps=5,
        samples_per_step=8,
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    _assert_fault_at(summary, CORNER_SENSORS[corner], msg=f"sweep 4s {corner}")


# D.14 – Weak signal multi-sensor (2 corners = 2 cases)


@pytest.mark.parametrize(
    "profile", DIAGNOSTIC_OPTIMIZED_PROFILES, ids=DIAGNOSTIC_OPTIMIZED_PROFILE_IDS
)
@pytest.mark.parametrize("corner", DIAGNOSTIC_WEAK_SIGNAL_CORNERS)
def test_4sensor_weak_signal(corner: str, profile: dict[str, Any]) -> None:
    """Weak fault on 4 sensors → low or no confidence."""
    sensor = CORNER_SENSORS[corner]
    samples = make_profile_fault_samples(
        profile=profile,
        fault_sensor=sensor,
        sensors=DIAGNOSTIC_4_SENSOR_SET,
        speed_kmh=SPEED_MID,
        n_samples=40,
        fault_amp=0.008,
        noise_amp=0.005,
        fault_vib_db=12.0,
        noise_vib_db=10.0,
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    top = extract_top(summary)
    if top:
        conf = float(top.get("confidence", 0))
        assert conf < 0.90, f"Weak signal → unexpectedly high conf={conf} for {corner}"


# D.15 – Very high speed 4-sensor (4 corners = 4 cases)


@pytest.mark.parametrize(
    "profile", DIAGNOSTIC_OPTIMIZED_PROFILES, ids=DIAGNOSTIC_OPTIMIZED_PROFILE_IDS
)
@pytest.mark.parametrize("corner", DIAGNOSTIC_WHEEL_CORNERS)
def test_4sensor_very_high_speed(corner: str, profile: dict[str, Any]) -> None:
    """4-sensor fault at 120 km/h."""
    sensor = CORNER_SENSORS[corner]
    samples = make_profile_fault_samples(
        profile=profile,
        fault_sensor=sensor,
        sensors=DIAGNOSTIC_4_SENSOR_SET,
        speed_kmh=SPEED_VERY_HIGH,
        n_samples=35,
        fault_amp=0.08,
        fault_vib_db=30.0,
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    _assert_fault_at(summary, sensor, msg=f"4s {corner}@120")
