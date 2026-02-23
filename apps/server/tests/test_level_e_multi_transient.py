# ruff: noqa: E501
"""Level E – Multiple sensors, transient (≥50 direct-injection cases).

Tests the analysis pipeline with MULTIPLE sensors (2, 4, 8, 12) and
TRANSIENT events present.  Validates transient de-weighting, persistent
fault preservation under spatial noise, and confidence calibration.
"""

from __future__ import annotations

from typing import Any

import pytest
from builders import (
    ALL_WHEEL_SENSORS,
    CAR_PROFILE_IDS,
    CAR_PROFILES,
    CORNER_SENSORS,
    NON_WHEEL_SENSORS,
    SENSOR_FL,
    SENSOR_FR,
    SENSOR_RL,
    SENSOR_RR,
    SPEED_HIGH,
    SPEED_LOW,
    SPEED_MID,
    SPEED_VERY_HIGH,
    assert_confidence_label_valid,
    assert_diagnosis_contract,
    assert_strongest_location,
    assert_tolerant_no_fault,
    assert_wheel_source,
    extract_top,
    make_diffuse_samples,
    make_idle_samples,
    make_noise_samples,
    make_profile_fault_samples,
    make_profile_speed_sweep_fault_samples,
    make_ramp_samples,
    make_transient_samples,
    profile_metadata,
    run_analysis,
)

# Sensor sets
_4S = ALL_WHEEL_SENSORS[:]
_8S = ALL_WHEEL_SENSORS + NON_WHEEL_SENSORS[:4]
_12S = ALL_WHEEL_SENSORS + NON_WHEEL_SENSORS[:8]
_2S_FL_RR = [SENSOR_FL, SENSOR_RR]

_CORNERS = ["FL", "FR", "RL", "RR"]
_SPEEDS = [SPEED_LOW, SPEED_MID, SPEED_HIGH]


# ---------------------------------------------------------------------------
# E.1 – 4-sensor fault + transient at each corner × speed (4×3 = 12 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", _CORNERS)
@pytest.mark.parametrize("speed", _SPEEDS, ids=["low", "mid", "high"])
def test_4sensor_fault_with_transient(corner: str, speed: float, profile: dict[str, Any]) -> None:
    """4 sensors, fault at corner + transient → fault preserved."""
    sensor = CORNER_SENSORS[corner]
    samples: list[dict] = []
    samples.extend(
        make_profile_fault_samples(
            profile=profile,
            fault_sensor=sensor,
            sensors=_4S,
            speed_kmh=speed,
            n_samples=30,
            start_t_s=0,
            fault_amp=0.07,
            fault_vib_db=28.0,
        )
    )
    # Transient on the same fault sensor
    samples.extend(
        make_transient_samples(
            sensor=sensor,
            speed_kmh=speed,
            n_samples=3,
            start_t_s=12,
            spike_amp=0.18,
            spike_vib_db=36.0,
        )
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    top = extract_top(summary)
    assert top is not None, f"Lost 4sensor fault+transient {corner}@{speed}"
    assert_diagnosis_contract(
        summary,
        expected_source="wheel",
        expected_sensor=sensor,
        min_confidence=0.15,
        msg=f"4s+t {corner}@{speed}",
    )


# ---------------------------------------------------------------------------
# E.2 – 4-sensor transient on non-fault sensor (4 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", _CORNERS)
def test_4sensor_transient_on_other_sensor(corner: str, profile: dict[str, Any]) -> None:
    """Transient on a different sensor from the fault → fault still detected."""
    sensor = CORNER_SENSORS[corner]
    other = SENSOR_RR if corner != "RR" else SENSOR_FL
    samples: list[dict] = []
    samples.extend(
        make_profile_fault_samples(
            profile=profile,
            fault_sensor=sensor,
            sensors=_4S,
            speed_kmh=SPEED_MID,
            n_samples=35,
            start_t_s=0,
            fault_amp=0.07,
            fault_vib_db=28.0,
        )
    )
    samples.extend(
        make_transient_samples(
            sensor=other,
            speed_kmh=SPEED_MID,
            n_samples=3,
            start_t_s=15,
            spike_amp=0.20,
            spike_vib_db=38.0,
        )
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    top = extract_top(summary)
    assert top is not None, f"Lost fault when transient on other sensor {corner}"
    assert_wheel_source(summary, msg=f"4s other-t {corner}")
    assert_strongest_location(summary, sensor, msg=f"4s other-t {corner}")


# ---------------------------------------------------------------------------
# E.3 – 4-sensor no-fault + transient → no persistent fault (3 speeds = 3 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize("speed", _SPEEDS, ids=["low", "mid", "high"])
def test_4sensor_transient_only_no_fault(speed: float, profile: dict[str, Any]) -> None:
    """4 sensors, road noise + transient → no persistent wheel fault."""
    samples: list[dict] = []
    samples.extend(make_noise_samples(sensors=_4S, speed_kmh=speed, n_samples=35))
    samples.extend(
        make_transient_samples(
            sensor=SENSOR_FL,
            speed_kmh=speed,
            n_samples=3,
            start_t_s=35,
            spike_amp=0.15,
            spike_vib_db=35.0,
        )
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    assert_tolerant_no_fault(summary, msg=f"4sensor transient-only@{speed}")


# ---------------------------------------------------------------------------
# E.4 – 8-sensor fault + transient (4 corners = 4 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", _CORNERS)
def test_8sensor_fault_with_transient(corner: str, profile: dict[str, Any]) -> None:
    """8 sensors, fault at one corner + transient → correct detection."""
    sensor = CORNER_SENSORS[corner]
    samples: list[dict] = []
    samples.extend(
        make_profile_fault_samples(
            profile=profile,
            fault_sensor=sensor,
            sensors=_8S,
            speed_kmh=SPEED_HIGH,
            n_samples=30,
            start_t_s=0,
            fault_amp=0.07,
            fault_vib_db=28.0,
        )
    )
    samples.extend(
        make_transient_samples(
            sensor=sensor,
            speed_kmh=SPEED_HIGH,
            n_samples=3,
            start_t_s=12,
            spike_amp=0.20,
            spike_vib_db=38.0,
        )
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    top = extract_top(summary)
    assert top is not None, f"Lost 8sensor fault+transient {corner}"
    assert_wheel_source(summary, msg=f"8s+t {corner}")
    assert_strongest_location(summary, sensor, msg=f"8s+t {corner}")
    assert_confidence_label_valid(summary, msg=f"8s+t {corner}")


# ---------------------------------------------------------------------------
# E.5 – 12-sensor fault + transient (4 corners = 4 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", _CORNERS)
def test_12sensor_fault_with_transient(corner: str, profile: dict[str, Any]) -> None:
    """12 sensors, fault at one corner + transient → correct detection."""
    sensor = CORNER_SENSORS[corner]
    samples: list[dict] = []
    samples.extend(
        make_profile_fault_samples(
            profile=profile,
            fault_sensor=sensor,
            sensors=_12S,
            speed_kmh=SPEED_HIGH,
            n_samples=30,
            start_t_s=0,
            fault_amp=0.07,
            fault_vib_db=28.0,
        )
    )
    samples.extend(
        make_transient_samples(
            sensor=sensor,
            speed_kmh=SPEED_HIGH,
            n_samples=3,
            start_t_s=12,
            spike_amp=0.18,
            spike_vib_db=36.0,
        )
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    top = extract_top(summary)
    assert top is not None, f"Lost 12sensor fault+transient {corner}"
    assert_wheel_source(summary, msg=f"12s+t {corner}")
    assert_strongest_location(summary, sensor, msg=f"12s+t {corner}")


# ---------------------------------------------------------------------------
# E.6 – 2-sensor fault + transient (2 pairs × 2 faults = 4 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize(
    "sensors,fault_corner",
    [
        (_2S_FL_RR, "FL"),
        (_2S_FL_RR, "RR"),
        ([SENSOR_FR, SENSOR_RL], "FR"),
        ([SENSOR_FR, SENSOR_RL], "RL"),
    ],
    ids=["FL_2s", "RR_2s", "FR_2s", "RL_2s"],
)
def test_2sensor_fault_with_transient(
    sensors: list[str], fault_corner: str, profile: dict[str, Any]
) -> None:
    """2-sensor pair, fault + transient → fault still detected."""
    fault_sensor = CORNER_SENSORS[fault_corner]
    samples: list[dict] = []
    samples.extend(
        make_profile_fault_samples(
            profile=profile,
            fault_sensor=fault_sensor,
            sensors=sensors,
            speed_kmh=SPEED_MID,
            n_samples=35,
            start_t_s=0,
            fault_amp=0.07,
            fault_vib_db=28.0,
        )
    )
    samples.extend(
        make_transient_samples(
            sensor=fault_sensor,
            speed_kmh=SPEED_MID,
            n_samples=3,
            start_t_s=15,
            spike_amp=0.18,
            spike_vib_db=36.0,
        )
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    top = extract_top(summary)
    assert top is not None, f"Lost 2sensor fault+transient {fault_corner}"
    assert_wheel_source(summary, msg=f"2s+t {fault_corner}")
    assert_strongest_location(summary, fault_sensor, msg=f"2s+t {fault_corner}")


# ---------------------------------------------------------------------------
# E.7 – Diffuse + transient on 4 sensors (3 speeds = 3 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize("speed", _SPEEDS, ids=["low", "mid", "high"])
def test_4sensor_diffuse_transient_no_fault(speed: float, profile: dict[str, Any]) -> None:
    """Diffuse excitation + transient on 4 sensors → no wheel fault."""
    samples: list[dict] = []
    samples.extend(make_diffuse_samples(sensors=_4S, speed_kmh=speed, n_samples=35))
    samples.extend(
        make_transient_samples(
            sensor=SENSOR_FR,
            speed_kmh=speed,
            n_samples=3,
            start_t_s=35,
            spike_amp=0.15,
            spike_vib_db=35.0,
        )
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    assert_tolerant_no_fault(summary, msg=f"4s-diffuse+transient@{speed}")


# ---------------------------------------------------------------------------
# E.8 – Multiple transients on multiple sensors (4 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", _CORNERS)
def test_4sensor_multi_transient_preserves_fault(corner: str, profile: dict[str, Any]) -> None:
    """Fault + transients on TWO sensors → fault still detected."""
    sensor = CORNER_SENSORS[corner]
    other = SENSOR_RR if corner != "RR" else SENSOR_FL
    samples: list[dict] = []
    samples.extend(
        make_profile_fault_samples(
            profile=profile,
            fault_sensor=sensor,
            sensors=_4S,
            speed_kmh=SPEED_MID,
            n_samples=30,
            start_t_s=0,
            fault_amp=0.07,
            fault_vib_db=28.0,
        )
    )
    # Transient on fault sensor
    samples.extend(
        make_transient_samples(
            sensor=sensor,
            speed_kmh=SPEED_MID,
            n_samples=3,
            start_t_s=10,
            spike_amp=0.15,
            spike_vib_db=35.0,
        )
    )
    # Transient on another sensor
    samples.extend(
        make_transient_samples(
            sensor=other,
            speed_kmh=SPEED_MID,
            n_samples=3,
            start_t_s=20,
            spike_amp=0.12,
            spike_vib_db=33.0,
        )
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    top = extract_top(summary)
    assert top is not None, f"Multi-transient lost fault {corner}"
    assert_wheel_source(summary, msg=f"multi-t {corner}")
    assert_strongest_location(summary, sensor, msg=f"multi-t {corner}")


# ---------------------------------------------------------------------------
# E.9 – Phased onset + transient on 4 sensors (2 corners = 2 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", ["FL", "RR"])
def test_4sensor_phased_onset_with_transient(corner: str, profile: dict[str, Any]) -> None:
    """Idle → ramp → fault + transient on 4 sensors."""
    sensor = CORNER_SENSORS[corner]
    samples: list[dict] = []
    samples.extend(make_idle_samples(sensors=_4S, n_samples=6, start_t_s=0))
    samples.extend(
        make_ramp_samples(sensors=_4S, speed_start=20, speed_end=80, n_samples=10, start_t_s=6)
    )
    samples.extend(
        make_profile_fault_samples(
            profile=profile,
            fault_sensor=sensor,
            sensors=_4S,
            speed_kmh=80.0,
            n_samples=25,
            start_t_s=16,
            fault_amp=0.07,
            fault_vib_db=28.0,
        )
    )
    samples.extend(
        make_transient_samples(
            sensor=sensor,
            speed_kmh=80.0,
            n_samples=3,
            start_t_s=28,
            spike_amp=0.18,
            spike_vib_db=36.0,
        )
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    top = extract_top(summary)
    assert top is not None, f"Phased+transient lost {corner}"
    assert_wheel_source(summary, msg=f"phased+t {corner}")
    assert_strongest_location(summary, sensor, msg=f"phased+t {corner}")


# ---------------------------------------------------------------------------
# E.10 – Transfer path + transient (4 corners = 4 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", _CORNERS)
def test_4sensor_transfer_with_transient(corner: str, profile: dict[str, Any]) -> None:
    """Fault with 20% leak + transient → correct source still identified."""
    sensor = CORNER_SENSORS[corner]
    samples: list[dict] = []
    samples.extend(
        make_profile_fault_samples(
            profile=profile,
            fault_sensor=sensor,
            sensors=_4S,
            speed_kmh=SPEED_MID,
            n_samples=30,
            start_t_s=0,
            fault_amp=0.07,
            fault_vib_db=28.0,
            transfer_fraction=0.2,
        )
    )
    samples.extend(
        make_transient_samples(
            sensor=sensor,
            speed_kmh=SPEED_MID,
            n_samples=3,
            start_t_s=12,
            spike_amp=0.15,
            spike_vib_db=35.0,
        )
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    top = extract_top(summary)
    assert top is not None, f"Transfer+transient lost {corner}"
    assert_wheel_source(summary, msg=f"xfer+t {corner}")
    assert_strongest_location(summary, sensor, msg=f"xfer+t {corner}")


# ---------------------------------------------------------------------------
# E.11 – Very high speed + transient on 8 sensors (2 corners = 2 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", ["FR", "RL"])
def test_8sensor_vhigh_speed_transient(corner: str, profile: dict[str, Any]) -> None:
    """8 sensors at 120 km/h with fault + transient."""
    sensor = CORNER_SENSORS[corner]
    samples: list[dict] = []
    samples.extend(
        make_profile_fault_samples(
            profile=profile,
            fault_sensor=sensor,
            sensors=_8S,
            speed_kmh=SPEED_VERY_HIGH,
            n_samples=30,
            start_t_s=0,
            fault_amp=0.08,
            fault_vib_db=30.0,
        )
    )
    samples.extend(
        make_transient_samples(
            sensor=sensor,
            speed_kmh=SPEED_VERY_HIGH,
            n_samples=3,
            start_t_s=12,
            spike_amp=0.20,
            spike_vib_db=38.0,
        )
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    top = extract_top(summary)
    assert top is not None, f"8sensor vhigh+transient lost {corner}"
    assert_wheel_source(summary, msg=f"8s vhigh+t {corner}")
    assert_strongest_location(summary, sensor, msg=f"8s vhigh+t {corner}")


# ---------------------------------------------------------------------------
# E.12 – 12-sensor no-fault + transient → no fault (2 speeds = 2 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize("speed", [SPEED_LOW, SPEED_HIGH], ids=["low", "high"])
def test_12sensor_transient_only_no_fault(speed: float, profile: dict[str, Any]) -> None:
    """12 sensors, road noise + transient → no persistent wheel fault."""
    samples: list[dict] = []
    samples.extend(make_noise_samples(sensors=_12S, speed_kmh=speed, n_samples=35))
    samples.extend(
        make_transient_samples(
            sensor=SENSOR_FL,
            speed_kmh=speed,
            n_samples=3,
            start_t_s=35,
            spike_amp=0.15,
            spike_vib_db=35.0,
        )
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    assert_tolerant_no_fault(summary, msg=f"12sensor transient-only@{speed}")


# ---------------------------------------------------------------------------
# E.13 – Speed sweep with transient on 4 sensors (2 corners = 2 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", ["FL", "RL"])
def test_4sensor_speed_sweep_with_transient(corner: str, profile: dict[str, Any]) -> None:
    """Speed sweep fault + transient on 4 sensors → detected."""
    sensor = CORNER_SENSORS[corner]
    samples = make_profile_speed_sweep_fault_samples(
        profile=profile,
        fault_sensor=sensor,
        sensors=_4S,
        speed_start=40,
        speed_end=100,
        n_steps=5,
        samples_per_step=8,
    )
    samples.extend(
        make_transient_samples(
            sensor=sensor,
            speed_kmh=70.0,
            n_samples=3,
            start_t_s=20,
            spike_amp=0.18,
            spike_vib_db=36.0,
        )
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    top = extract_top(summary)
    assert top is not None, f"Speed sweep+transient lost {corner}"
    assert_wheel_source(summary, msg=f"sweep+t {corner}")
    assert_strongest_location(summary, CORNER_SENSORS[corner], msg=f"sweep+t {corner}")
