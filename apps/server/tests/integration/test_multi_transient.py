"""Multi-sensor transient scenarios that stay distinct after matrix consolidation.

Representative corner/speed, no-fault baseline, and phased-onset coverage now
lives in ``test_synthetic_scenario_matrix.py``. This module keeps the
multi-sensor transient behaviors that remain unique.
"""

from __future__ import annotations

from typing import Any

import pytest
from test_support import (
    CORNER_SENSORS,
    SENSOR_FL,
    SENSOR_FR,
    SENSOR_RR,
    SPEED_HIGH,
    SPEED_MID,
    SPEED_VERY_HIGH,
    assert_confidence_label_valid,
    assert_strongest_location,
    assert_tolerant_no_fault,
    assert_wheel_source,
    extract_top,
    make_diffuse_samples,
    make_profile_fault_samples,
    make_profile_speed_sweep_fault_samples,
    make_transient_samples,
    profile_metadata,
    run_analysis,
)
from test_support.diagnostic_matrix_catalogs import (
    DIAGNOSTIC_4_SENSOR_SET,
    DIAGNOSTIC_8_SENSOR_SET,
    DIAGNOSTIC_12_SENSOR_SET,
    DIAGNOSTIC_OPTIMIZED_PROFILE_IDS,
    DIAGNOSTIC_OPTIMIZED_PROFILES,
    DIAGNOSTIC_STANDARD_SPEED_IDS,
    DIAGNOSTIC_TWO_SENSOR_LOCALIZATION_CASES,
    DIAGNOSTIC_WHEEL_CORNERS,
    TRANSIENT_SPEED_SWEEP_CORNERS,
    TRANSIENT_VERY_HIGH_SPEED_CORNERS,
)
from test_support.diagnostic_matrix_catalogs import (
    DIAGNOSTIC_4_SENSOR_SET as _4S,
)
from test_support.diagnostic_matrix_catalogs import (
    DIAGNOSTIC_8_SENSOR_SET as _8S,
)
from test_support.diagnostic_matrix_catalogs import (
    DIAGNOSTIC_OPTIMIZED_PROFILE_IDS as _OPTIMIZED_CAR_PROFILE_IDS,
)
from test_support.diagnostic_matrix_catalogs import (
    DIAGNOSTIC_OPTIMIZED_PROFILES as _OPTIMIZED_CAR_PROFILES,
)
from test_support.diagnostic_matrix_catalogs import (
    DIAGNOSTIC_STANDARD_SPEEDS as _SPEEDS,
)
from test_support.diagnostic_matrix_catalogs import (
    DIAGNOSTIC_WHEEL_CORNERS as _CORNERS,
)

# Helpers


def _assert_fault_at(summary: dict[str, Any], sensor: str, msg: str) -> None:
    """Common assertion: top finding exists at *sensor* with wheel source."""
    top = extract_top(summary)
    assert top is not None, f"{msg}: no finding"
    assert_wheel_source(summary, msg=msg)
    assert_strongest_location(summary, sensor, msg=msg)


# E.2 – 4-sensor transient on non-fault sensor (4 cases)


@pytest.mark.parametrize(
    "profile", DIAGNOSTIC_OPTIMIZED_PROFILES, ids=DIAGNOSTIC_OPTIMIZED_PROFILE_IDS
)
@pytest.mark.parametrize("corner", DIAGNOSTIC_WHEEL_CORNERS)
def test_4sensor_transient_on_other_sensor(corner: str, profile: dict[str, Any]) -> None:
    """Transient on a different sensor from the fault → fault still detected."""
    sensor = CORNER_SENSORS[corner]
    other = SENSOR_RR if corner != "RR" else SENSOR_FL
    samples: list[dict] = []
    samples.extend(
        make_profile_fault_samples(
            profile=profile,
            fault_sensor=sensor,
            sensors=DIAGNOSTIC_4_SENSOR_SET,
            speed_kmh=SPEED_MID,
            n_samples=35,
            start_t_s=0,
            fault_amp=0.07,
            fault_vib_db=28.0,
        ),
    )
    samples.extend(
        make_transient_samples(
            sensor=other,
            speed_kmh=SPEED_MID,
            n_samples=3,
            start_t_s=15,
            spike_amp=0.20,
            spike_vib_db=38.0,
        ),
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    _assert_fault_at(summary, sensor, msg=f"4s other-t {corner}")


# E.4 – 8-sensor fault + transient (4 corners = 4 cases)


@pytest.mark.parametrize(
    "profile", DIAGNOSTIC_OPTIMIZED_PROFILES, ids=DIAGNOSTIC_OPTIMIZED_PROFILE_IDS
)
@pytest.mark.parametrize("corner", DIAGNOSTIC_WHEEL_CORNERS)
def test_8sensor_fault_with_transient(corner: str, profile: dict[str, Any]) -> None:
    """8 sensors, fault at one corner + transient → correct detection."""
    sensor = CORNER_SENSORS[corner]
    samples: list[dict] = []
    samples.extend(
        make_profile_fault_samples(
            profile=profile,
            fault_sensor=sensor,
            sensors=DIAGNOSTIC_8_SENSOR_SET,
            speed_kmh=SPEED_HIGH,
            n_samples=30,
            start_t_s=0,
            fault_amp=0.07,
            fault_vib_db=28.0,
        ),
    )
    samples.extend(
        make_transient_samples(
            sensor=sensor,
            speed_kmh=SPEED_HIGH,
            n_samples=3,
            start_t_s=12,
            spike_amp=0.20,
            spike_vib_db=38.0,
        ),
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    _assert_fault_at(summary, sensor, msg=f"8s+t {corner}")
    assert_confidence_label_valid(summary, msg=f"8s+t {corner}")


# E.5 – 12-sensor fault + transient (4 corners = 4 cases)


@pytest.mark.parametrize(
    "profile", DIAGNOSTIC_OPTIMIZED_PROFILES, ids=DIAGNOSTIC_OPTIMIZED_PROFILE_IDS
)
@pytest.mark.parametrize("corner", DIAGNOSTIC_WHEEL_CORNERS)
def test_12sensor_fault_with_transient(corner: str, profile: dict[str, Any]) -> None:
    """12 sensors, fault at one corner + transient → correct detection."""
    sensor = CORNER_SENSORS[corner]
    samples: list[dict] = []
    samples.extend(
        make_profile_fault_samples(
            profile=profile,
            fault_sensor=sensor,
            sensors=DIAGNOSTIC_12_SENSOR_SET,
            speed_kmh=SPEED_HIGH,
            n_samples=30,
            start_t_s=0,
            fault_amp=0.07,
            fault_vib_db=28.0,
        ),
    )
    samples.extend(
        make_transient_samples(
            sensor=sensor,
            speed_kmh=SPEED_HIGH,
            n_samples=3,
            start_t_s=12,
            spike_amp=0.18,
            spike_vib_db=36.0,
        ),
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    _assert_fault_at(summary, sensor, msg=f"12s+t {corner}")


# E.6 – 2-sensor fault + transient (2 pairs × 2 faults = 4 cases)


@pytest.mark.parametrize("profile", _OPTIMIZED_CAR_PROFILES, ids=_OPTIMIZED_CAR_PROFILE_IDS)
@pytest.mark.parametrize(
    ("sensors", "fault_corner"),
    [
        (sensors, fault_corner)
        for _, sensors, fault_corner in DIAGNOSTIC_TWO_SENSOR_LOCALIZATION_CASES
    ],
    ids=[case_id for case_id, _, _ in DIAGNOSTIC_TWO_SENSOR_LOCALIZATION_CASES],
)
def test_2sensor_fault_with_transient(
    sensors: list[str],
    fault_corner: str,
    profile: dict[str, Any],
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
        ),
    )
    samples.extend(
        make_transient_samples(
            sensor=fault_sensor,
            speed_kmh=SPEED_MID,
            n_samples=3,
            start_t_s=15,
            spike_amp=0.18,
            spike_vib_db=36.0,
        ),
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    _assert_fault_at(summary, fault_sensor, msg=f"2s+t {fault_corner}")


# E.7 – Diffuse + transient on 4 sensors (3 speeds = 3 cases)


@pytest.mark.parametrize("profile", _OPTIMIZED_CAR_PROFILES, ids=_OPTIMIZED_CAR_PROFILE_IDS)
@pytest.mark.parametrize("speed", _SPEEDS, ids=DIAGNOSTIC_STANDARD_SPEED_IDS)
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
        ),
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    assert_tolerant_no_fault(summary, msg=f"4s-diffuse+transient@{speed}")


# E.8 – Multiple transients on multiple sensors (4 cases)


@pytest.mark.parametrize("profile", _OPTIMIZED_CAR_PROFILES, ids=_OPTIMIZED_CAR_PROFILE_IDS)
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
        ),
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
        ),
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
        ),
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    _assert_fault_at(summary, sensor, msg=f"multi-t {corner}")


# E.10 – Transfer path + transient (4 corners = 4 cases)


@pytest.mark.parametrize("profile", _OPTIMIZED_CAR_PROFILES, ids=_OPTIMIZED_CAR_PROFILE_IDS)
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
        ),
    )
    samples.extend(
        make_transient_samples(
            sensor=sensor,
            speed_kmh=SPEED_MID,
            n_samples=3,
            start_t_s=12,
            spike_amp=0.15,
            spike_vib_db=35.0,
        ),
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    _assert_fault_at(summary, sensor, msg=f"xfer+t {corner}")


# E.11 – Very high speed + transient on 8 sensors (2 corners = 2 cases)


@pytest.mark.parametrize("profile", _OPTIMIZED_CAR_PROFILES, ids=_OPTIMIZED_CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", TRANSIENT_VERY_HIGH_SPEED_CORNERS)
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
        ),
    )
    samples.extend(
        make_transient_samples(
            sensor=sensor,
            speed_kmh=SPEED_VERY_HIGH,
            n_samples=3,
            start_t_s=12,
            spike_amp=0.20,
            spike_vib_db=38.0,
        ),
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    _assert_fault_at(summary, sensor, msg=f"8s vhigh+t {corner}")


# E.13 – Speed sweep with transient on 4 sensors (2 corners = 2 cases)


@pytest.mark.parametrize("profile", _OPTIMIZED_CAR_PROFILES, ids=_OPTIMIZED_CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", TRANSIENT_SPEED_SWEEP_CORNERS)
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
        ),
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    _assert_fault_at(summary, CORNER_SENSORS[corner], msg=f"sweep+t {corner}")
