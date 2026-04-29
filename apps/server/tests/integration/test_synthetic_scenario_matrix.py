"""Representative synthetic scenario matrix coverage.

This module owns the cross-cutting synthetic scenario dimensions that were
previously duplicated across the single-vs-multi and transient-vs-steady
integration suites:

- core fault corner/speed detection
- no-fault noise baselines
- phased onset behavior

The 4-sensor steady matrix remains the full corner x speed owner. Single-sensor
and transient variants keep representative subsets so the suite still covers
those dimensions without repeating the entire cartesian product.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pytest
from test_support import (
    CORNER_SENSORS,
    SENSOR_FL,
    assert_confidence_between,
    assert_confidence_label_valid,
    assert_has_warnings,
    assert_no_wheel_fault,
    assert_strongest_location,
    assert_tolerant_no_fault,
    assert_wheel_source,
    extract_top,
    make_idle_samples,
    make_noise_samples,
    make_profile_fault_samples,
    make_ramp_samples,
    make_transient_samples,
    profile_metadata,
    run_analysis,
)
from test_support.diagnostic_matrix_catalogs import (
    DIAGNOSTIC_4_SENSOR_SET,
    DIAGNOSTIC_12_SENSOR_SET,
    DIAGNOSTIC_OPTIMIZED_PROFILE_IDS,
    DIAGNOSTIC_OPTIMIZED_PROFILES,
    DIAGNOSTIC_REPRESENTATIVE_CORNERS,
    DIAGNOSTIC_REPRESENTATIVE_SPEED_CASES,
    DIAGNOSTIC_STANDARD_SPEED_CASES,
    DIAGNOSTIC_WHEEL_CORNERS,
)

SensorLayout = Literal["single", "4sensor", "12sensor"]


@dataclass(frozen=True, slots=True)
class _FaultMatrixCase:
    case_id: str
    sensor_layout: Literal["single", "4sensor"]
    corner: str
    speed_case_id: str
    speed_kmh: float
    transient: bool
    min_confidence: float
    expect_warnings: bool
    expect_confidence_label: bool


def _fault_case(
    *,
    case_id: str,
    sensor_layout: Literal["single", "4sensor"],
    corner: str,
    speed_case_id: str,
    speed_kmh: float,
    transient: bool,
    min_confidence: float,
    expect_warnings: bool = False,
    expect_confidence_label: bool = False,
) -> pytest.ParameterSet:
    return pytest.param(
        _FaultMatrixCase(
            case_id=case_id,
            sensor_layout=sensor_layout,
            corner=corner,
            speed_case_id=speed_case_id,
            speed_kmh=speed_kmh,
            transient=transient,
            min_confidence=min_confidence,
            expect_warnings=expect_warnings,
            expect_confidence_label=expect_confidence_label,
        ),
        id=f"{case_id}-{corner}-{speed_case_id}",
    )


FAULT_MATRIX_CASES = [
    *[
        _fault_case(
            case_id="4sensor-core",
            sensor_layout="4sensor",
            corner=corner,
            speed_case_id=speed_case_id,
            speed_kmh=speed_kmh,
            transient=False,
            min_confidence=0.15,
        )
        for corner in DIAGNOSTIC_WHEEL_CORNERS
        for speed_case_id, speed_kmh in DIAGNOSTIC_STANDARD_SPEED_CASES
    ],
    *[
        _fault_case(
            case_id="single-representative",
            sensor_layout="single",
            corner=corner,
            speed_case_id=speed_case_id,
            speed_kmh=speed_kmh,
            transient=False,
            min_confidence=0.45,
            expect_warnings=True,
            expect_confidence_label=True,
        )
        for corner in DIAGNOSTIC_REPRESENTATIVE_CORNERS
        for speed_case_id, speed_kmh in DIAGNOSTIC_REPRESENTATIVE_SPEED_CASES
    ],
    *[
        _fault_case(
            case_id="single-transient-representative",
            sensor_layout="single",
            corner=corner,
            speed_case_id=speed_case_id,
            speed_kmh=speed_kmh,
            transient=True,
            min_confidence=0.30,
            expect_warnings=True,
            expect_confidence_label=True,
        )
        for corner in DIAGNOSTIC_REPRESENTATIVE_CORNERS
        for speed_case_id, speed_kmh in DIAGNOSTIC_REPRESENTATIVE_SPEED_CASES
    ],
    *[
        _fault_case(
            case_id="4sensor-transient-representative",
            sensor_layout="4sensor",
            corner=corner,
            speed_case_id=speed_case_id,
            speed_kmh=speed_kmh,
            transient=True,
            min_confidence=0.15,
        )
        for corner in DIAGNOSTIC_REPRESENTATIVE_CORNERS
        for speed_case_id, speed_kmh in DIAGNOSTIC_REPRESENTATIVE_SPEED_CASES
    ],
]


@dataclass(frozen=True, slots=True)
class _NoFaultMatrixCase:
    case_id: str
    sensor_layout: SensorLayout
    speed_case_id: str
    speed_kmh: float
    transient: bool
    expect_warnings: bool


def _no_fault_case(
    *,
    case_id: str,
    sensor_layout: SensorLayout,
    speed_case_id: str,
    speed_kmh: float,
    transient: bool,
    expect_warnings: bool = False,
) -> pytest.ParameterSet:
    return pytest.param(
        _NoFaultMatrixCase(
            case_id=case_id,
            sensor_layout=sensor_layout,
            speed_case_id=speed_case_id,
            speed_kmh=speed_kmh,
            transient=transient,
            expect_warnings=expect_warnings,
        ),
        id=f"{case_id}-{speed_case_id}",
    )


NO_FAULT_MATRIX_CASES = [
    *[
        _no_fault_case(
            case_id="single-noise-baseline",
            sensor_layout="single",
            speed_case_id=speed_case_id,
            speed_kmh=speed_kmh,
            transient=False,
            expect_warnings=True,
        )
        for speed_case_id, speed_kmh in DIAGNOSTIC_REPRESENTATIVE_SPEED_CASES
    ],
    *[
        _no_fault_case(
            case_id="4sensor-noise-baseline",
            sensor_layout="4sensor",
            speed_case_id=speed_case_id,
            speed_kmh=speed_kmh,
            transient=False,
        )
        for speed_case_id, speed_kmh in DIAGNOSTIC_REPRESENTATIVE_SPEED_CASES
    ],
    *[
        _no_fault_case(
            case_id="single-transient-baseline",
            sensor_layout="single",
            speed_case_id=speed_case_id,
            speed_kmh=speed_kmh,
            transient=True,
        )
        for speed_case_id, speed_kmh in DIAGNOSTIC_REPRESENTATIVE_SPEED_CASES
    ],
    *[
        _no_fault_case(
            case_id="4sensor-transient-baseline",
            sensor_layout="4sensor",
            speed_case_id=speed_case_id,
            speed_kmh=speed_kmh,
            transient=True,
        )
        for speed_case_id, speed_kmh in DIAGNOSTIC_REPRESENTATIVE_SPEED_CASES
    ],
    *[
        _no_fault_case(
            case_id="12sensor-transient-baseline",
            sensor_layout="12sensor",
            speed_case_id=speed_case_id,
            speed_kmh=speed_kmh,
            transient=True,
        )
        for speed_case_id, speed_kmh in DIAGNOSTIC_REPRESENTATIVE_SPEED_CASES
    ],
]


@dataclass(frozen=True, slots=True)
class _PhasedMatrixCase:
    case_id: str
    sensor_layout: Literal["single", "4sensor"]
    corner: str
    transient: bool


def _phased_case(
    *,
    case_id: str,
    sensor_layout: Literal["single", "4sensor"],
    corner: str,
    transient: bool,
) -> pytest.ParameterSet:
    return pytest.param(
        _PhasedMatrixCase(
            case_id=case_id,
            sensor_layout=sensor_layout,
            corner=corner,
            transient=transient,
        ),
        id=f"{case_id}-{corner}",
    )


PHASED_MATRIX_CASES = [
    *[
        _phased_case(
            case_id="single-phased",
            sensor_layout="single",
            corner=corner,
            transient=False,
        )
        for corner in DIAGNOSTIC_REPRESENTATIVE_CORNERS
    ],
    *[
        _phased_case(
            case_id="4sensor-phased",
            sensor_layout="4sensor",
            corner=corner,
            transient=False,
        )
        for corner in DIAGNOSTIC_REPRESENTATIVE_CORNERS
    ],
    *[
        _phased_case(
            case_id="single-phased-transient",
            sensor_layout="single",
            corner=corner,
            transient=True,
        )
        for corner in DIAGNOSTIC_REPRESENTATIVE_CORNERS
    ],
    *[
        _phased_case(
            case_id="4sensor-phased-transient",
            sensor_layout="4sensor",
            corner=corner,
            transient=True,
        )
        for corner in DIAGNOSTIC_REPRESENTATIVE_CORNERS
    ],
]


def _sensors_for_layout(layout: SensorLayout, fault_sensor: str) -> list[str]:
    if layout == "single":
        return [fault_sensor]
    if layout == "4sensor":
        return DIAGNOSTIC_4_SENSOR_SET
    return DIAGNOSTIC_12_SENSOR_SET


@pytest.mark.parametrize(
    "profile", DIAGNOSTIC_OPTIMIZED_PROFILES, ids=DIAGNOSTIC_OPTIMIZED_PROFILE_IDS
)
@pytest.mark.parametrize("case", FAULT_MATRIX_CASES)
def test_representative_fault_scenario_matrix(
    case: _FaultMatrixCase,
    profile: dict[str, Any],
) -> None:
    """Keep one representative owner for the duplicated fault corner/speed matrices."""
    fault_sensor = CORNER_SENSORS[case.corner]
    sensors = _sensors_for_layout(case.sensor_layout, fault_sensor)
    samples: list[dict[str, Any]] = []
    samples.extend(
        make_profile_fault_samples(
            profile=profile,
            fault_sensor=fault_sensor,
            sensors=sensors,
            speed_kmh=case.speed_kmh,
            n_samples=40 if case.sensor_layout == "single" and not case.transient else 35,
            fault_amp=0.07,
            fault_vib_db=28.0,
            noise_vib_db=8.0,
        ),
    )
    if case.transient:
        samples.extend(
            make_transient_samples(
                sensor=fault_sensor,
                speed_kmh=case.speed_kmh,
                n_samples=3,
                start_t_s=15 if case.sensor_layout == "single" else 12,
                spike_amp=0.20 if case.sensor_layout == "single" else 0.18,
                spike_vib_db=38.0 if case.sensor_layout == "single" else 36.0,
            ),
        )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    top = extract_top(summary)
    tag = f"{case.case_id}/{case.corner}/{case.speed_case_id}"
    assert top is not None, f"No finding for {tag}"
    assert_confidence_between(summary, case.min_confidence, 1.0, msg=tag)
    if case.sensor_layout == "4sensor":
        assert_wheel_source(summary, msg=tag)
        assert_strongest_location(summary, fault_sensor, msg=tag)
    if case.expect_confidence_label:
        assert_confidence_label_valid(summary, msg=tag)
    if case.expect_warnings:
        assert_has_warnings(summary, msg=tag)


@pytest.mark.parametrize(
    "profile", DIAGNOSTIC_OPTIMIZED_PROFILES, ids=DIAGNOSTIC_OPTIMIZED_PROFILE_IDS
)
@pytest.mark.parametrize("case", NO_FAULT_MATRIX_CASES)
def test_representative_no_fault_scenario_matrix(
    case: _NoFaultMatrixCase,
    profile: dict[str, Any],
) -> None:
    """Keep representative steady/transient noise baselines across sensor layouts."""
    sensors = _sensors_for_layout(case.sensor_layout, SENSOR_FL)
    samples: list[dict[str, Any]] = []
    samples.extend(make_noise_samples(sensors=sensors, speed_kmh=case.speed_kmh, n_samples=40))
    if case.transient:
        samples.extend(
            make_transient_samples(
                sensor=SENSOR_FL,
                speed_kmh=case.speed_kmh,
                n_samples=3,
                start_t_s=35,
                spike_amp=0.15,
                spike_vib_db=35.0,
            ),
        )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    tag = f"{case.case_id}/{case.speed_case_id}"
    if case.transient:
        assert_tolerant_no_fault(summary, msg=tag)
    else:
        assert_no_wheel_fault(summary, msg=tag)
    if case.expect_warnings:
        assert_has_warnings(summary, msg=tag)


@pytest.mark.parametrize(
    "profile", DIAGNOSTIC_OPTIMIZED_PROFILES, ids=DIAGNOSTIC_OPTIMIZED_PROFILE_IDS
)
@pytest.mark.parametrize("case", PHASED_MATRIX_CASES)
def test_representative_phased_scenario_matrix(
    case: _PhasedMatrixCase,
    profile: dict[str, Any],
) -> None:
    """Keep phased synthetic coverage without repeating every single/multi/transient combination."""
    fault_sensor = CORNER_SENSORS[case.corner]
    sensors = _sensors_for_layout(case.sensor_layout, fault_sensor)
    samples: list[dict[str, Any]] = []
    samples.extend(
        make_idle_samples(
            sensors=sensors,
            n_samples=10 if case.sensor_layout == "single" else 8,
            start_t_s=0,
        ),
    )
    samples.extend(
        make_ramp_samples(
            sensors=sensors,
            speed_start=20,
            speed_end=80,
            n_samples=15 if case.sensor_layout == "single" else 12,
            start_t_s=10 if case.sensor_layout == "single" else 8,
        ),
    )
    samples.extend(
        make_profile_fault_samples(
            profile=profile,
            fault_sensor=fault_sensor,
            sensors=sensors,
            speed_kmh=80.0,
            n_samples=35 if case.sensor_layout == "single" else 30,
            start_t_s=25 if case.sensor_layout == "single" else 20,
            fault_amp=0.07,
            fault_vib_db=28.0,
        ),
    )
    if case.transient:
        samples.extend(
            make_transient_samples(
                sensor=fault_sensor,
                speed_kmh=80.0,
                n_samples=3,
                start_t_s=30 if case.sensor_layout == "single" else 28,
                spike_amp=0.18,
                spike_vib_db=36.0,
            ),
        )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    tag = f"{case.case_id}/{case.corner}"
    top = extract_top(summary)
    assert top is not None, f"No finding for {tag}"
    assert_confidence_between(summary, 0.15, 1.0, msg=tag)
    if case.sensor_layout == "4sensor":
        assert_wheel_source(summary, msg=tag)
        assert_strongest_location(summary, fault_sensor, msg=tag)
