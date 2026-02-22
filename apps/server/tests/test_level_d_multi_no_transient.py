# ruff: noqa: E501
"""Level D – Multiple sensors, no transient (≥50 direct-injection cases).

Tests the analysis pipeline with MULTIPLE sensors (2, 4, 8, or 12) and
NO transient events.  Validates spatial localization, confidence scaling,
no-fault suppression, and diffuse excitation handling.
"""

from __future__ import annotations

import pytest
from builders import (
    ALL_WHEEL_SENSORS,
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
    assert_confidence_between,
    assert_diagnosis_contract,
    assert_no_wheel_fault,
    assert_pairwise_monotonic,
    assert_strongest_location,
    assert_wheel_source,
    extract_top,
    make_diffuse_samples,
    make_fault_samples,
    make_idle_samples,
    make_noise_samples,
    make_ramp_samples,
    run_analysis,
    top_confidence,
)

# ---------------------------------------------------------------------------
# Sensor set helpers
# ---------------------------------------------------------------------------

_2_SENSORS_FL_RR = [SENSOR_FL, SENSOR_RR]
_2_SENSORS_FR_RL = [SENSOR_FR, SENSOR_RL]
_4_SENSORS = ALL_WHEEL_SENSORS[:]
_8_SENSORS = ALL_WHEEL_SENSORS + NON_WHEEL_SENSORS[:4]
_12_SENSORS = ALL_WHEEL_SENSORS + NON_WHEEL_SENSORS[:8]

_CORNERS = ["FL", "FR", "RL", "RR"]
_SPEEDS = [SPEED_LOW, SPEED_MID, SPEED_HIGH]


# ---------------------------------------------------------------------------
# D.1 – 4-sensor fault at each corner × speed (4×3 = 12 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corner", _CORNERS)
@pytest.mark.parametrize("speed", _SPEEDS, ids=["low", "mid", "high"])
def test_4sensor_fault_corner_speed(corner: str, speed: float) -> None:
    """4 wheel sensors, fault at one corner across speed bands."""
    sensor = CORNER_SENSORS[corner]
    samples = make_fault_samples(
        fault_sensor=sensor,
        sensors=_4_SENSORS,
        speed_kmh=speed,
        n_samples=35,
        fault_amp=0.07,
        fault_vib_db=28.0,
        noise_vib_db=8.0,
    )
    summary = run_analysis(samples)
    assert_diagnosis_contract(
        summary,
        expected_source="wheel",
        expected_sensor=sensor,
        min_confidence=0.15,
        msg=f"4s {corner}@{speed}",
    )


# ---------------------------------------------------------------------------
# D.2 – 4-sensor no-fault baseline (3 speeds = 3 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("speed", _SPEEDS, ids=["low", "mid", "high"])
def test_4sensor_no_fault(speed: float) -> None:
    """4 sensors, all noise → no wheel fault."""
    samples = make_noise_samples(sensors=_4_SENSORS, speed_kmh=speed, n_samples=40)
    summary = run_analysis(samples)
    assert_no_wheel_fault(summary, msg=f"4sensor-no-fault@{speed}")


# ---------------------------------------------------------------------------
# D.3 – 2-sensor pairs with fault localization (4 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sensors,fault_corner",
    [
        (_2_SENSORS_FL_RR, "FL"),
        (_2_SENSORS_FL_RR, "RR"),
        (_2_SENSORS_FR_RL, "FR"),
        (_2_SENSORS_FR_RL, "RL"),
    ],
    ids=["FL_in_FL_RR", "RR_in_FL_RR", "FR_in_FR_RL", "RL_in_FR_RL"],
)
def test_2sensor_localization(sensors: list[str], fault_corner: str) -> None:
    """2-sensor pair, fault at one → correct localization."""
    fault_sensor = CORNER_SENSORS[fault_corner]
    samples = make_fault_samples(
        fault_sensor=fault_sensor,
        sensors=sensors,
        speed_kmh=SPEED_MID,
        n_samples=40,
        fault_amp=0.07,
        fault_vib_db=28.0,
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    assert top is not None, f"No finding for 2-sensor {fault_corner}"
    assert_wheel_source(summary, msg=f"2s {fault_corner}")
    assert_strongest_location(summary, fault_sensor, msg=f"2s {fault_corner}")


# ---------------------------------------------------------------------------
# D.4 – 8-sensor fault localization (4 corners = 4 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corner", _CORNERS)
def test_8sensor_fault_localization(corner: str) -> None:
    """8 sensors (4 wheel + 4 non-wheel), fault at one wheel corner."""
    sensor = CORNER_SENSORS[corner]
    samples = make_fault_samples(
        fault_sensor=sensor,
        sensors=_8_SENSORS,
        speed_kmh=SPEED_HIGH,
        n_samples=35,
        fault_amp=0.07,
        fault_vib_db=28.0,
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    assert top is not None, f"No finding for 8-sensor {corner}"
    assert_wheel_source(summary, msg=f"8s {corner}")
    assert_strongest_location(summary, sensor, msg=f"8s {corner}")


# ---------------------------------------------------------------------------
# D.5 – 12-sensor fault localization (4 corners = 4 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corner", _CORNERS)
def test_12sensor_fault_localization(corner: str) -> None:
    """12 sensors, fault at one wheel corner → correct localization."""
    sensor = CORNER_SENSORS[corner]
    samples = make_fault_samples(
        fault_sensor=sensor,
        sensors=_12_SENSORS,
        speed_kmh=SPEED_HIGH,
        n_samples=35,
        fault_amp=0.07,
        fault_vib_db=28.0,
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    assert top is not None, f"No finding for 12-sensor {corner}"
    assert_wheel_source(summary, msg=f"12s {corner}")
    assert_strongest_location(summary, sensor, msg=f"12s {corner}")


# ---------------------------------------------------------------------------
# D.6 – Diffuse excitation on 4 sensors → no wheel fault (3 speeds = 3 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("speed", _SPEEDS, ids=["low", "mid", "high"])
def test_4sensor_diffuse_no_fault(speed: float) -> None:
    """Diffuse excitation across 4 sensors → no localized wheel fault."""
    samples = make_diffuse_samples(sensors=_4_SENSORS, speed_kmh=speed, n_samples=40)
    summary = run_analysis(samples)
    assert_no_wheel_fault(summary, msg=f"4sensor-diffuse@{speed}")


# ---------------------------------------------------------------------------
# D.7 – Confidence scales with sensor count (3 sensor counts = 3 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sensors,label",
    [(_2_SENSORS_FL_RR, "2sensor"), (_4_SENSORS, "4sensor"), (_8_SENSORS, "8sensor")],
    ids=["2s", "4s", "8s"],
)
def test_confidence_scales_with_sensor_count(sensors: list[str], label: str) -> None:
    """More sensors → confidence should be reasonable (not inflated beyond reality)."""
    samples = make_fault_samples(
        fault_sensor=SENSOR_FL,
        sensors=sensors,
        speed_kmh=SPEED_HIGH,
        n_samples=35,
        fault_amp=0.07,
        fault_vib_db=28.0,
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    assert top is not None, f"No finding for {label}"
    assert_wheel_source(summary, msg=label)
    assert_confidence_between(summary, 0.10, 1.0, msg=label)


def test_sensor_count_monotonic() -> None:
    """Confidence for wheel/tire should not decrease as sensors are added (pairwise)."""
    confs: list[float] = []
    labels: list[str] = []
    for sensors, label in [(_2_SENSORS_FL_RR, "2s"), (_4_SENSORS, "4s"), (_8_SENSORS, "8s")]:
        samples = make_fault_samples(
            fault_sensor=SENSOR_FL,
            sensors=sensors,
            speed_kmh=SPEED_HIGH,
            n_samples=35,
            fault_amp=0.07,
            fault_vib_db=28.0,
        )
        summary = run_analysis(samples)
        confs.append(top_confidence(summary))
        labels.append(label)
    assert_pairwise_monotonic(confs, tolerance=0.05, labels=labels, msg="sensor-count")


# ---------------------------------------------------------------------------
# D.7b – Amplitude monotonic with 4 sensors (1 case)
# ---------------------------------------------------------------------------


def test_4sensor_amplitude_monotonic() -> None:
    """Wheel/tire confidence should increase pairwise with fault amplitude on 4 sensors."""
    confs: list[float] = []
    labels: list[str] = []
    for amp, vdb in [(0.03, 18.0), (0.06, 26.0), (0.12, 34.0)]:
        samples = make_fault_samples(
            fault_sensor=SENSOR_FL,
            sensors=_4_SENSORS,
            speed_kmh=SPEED_MID,
            n_samples=40,
            fault_amp=amp,
            fault_vib_db=vdb,
        )
        summary = run_analysis(samples)
        confs.append(top_confidence(summary))
        labels.append(f"amp={amp}")
    assert_pairwise_monotonic(confs, tolerance=0.05, labels=labels, msg="amplitude")


# ---------------------------------------------------------------------------
# D.8 – Transfer path leakage (fault + small leak to other sensors) (4 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corner", _CORNERS)
def test_4sensor_transfer_path(corner: str) -> None:
    """Fault + 20% amplitude leak to other sensors → correct source."""
    sensor = CORNER_SENSORS[corner]
    samples = make_fault_samples(
        fault_sensor=sensor,
        sensors=_4_SENSORS,
        speed_kmh=SPEED_MID,
        n_samples=35,
        fault_amp=0.07,
        fault_vib_db=28.0,
        transfer_fraction=0.2,
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    assert top is not None, f"No finding for transfer-path {corner}"
    assert_wheel_source(summary, msg=f"transfer {corner}")
    assert_strongest_location(summary, sensor, msg=f"transfer {corner}")


# ---------------------------------------------------------------------------
# D.9 – Phased onset multi-sensor (2 corners = 2 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corner", ["FL", "RR"])
def test_4sensor_phased_onset(corner: str) -> None:
    """Idle → ramp → fault on 4 sensors → correct detection."""
    sensor = CORNER_SENSORS[corner]
    samples: list[dict] = []
    samples.extend(make_idle_samples(sensors=_4_SENSORS, n_samples=8, start_t_s=0))
    samples.extend(
        make_ramp_samples(
            sensors=_4_SENSORS, speed_start=20, speed_end=80, n_samples=12, start_t_s=8
        )
    )
    samples.extend(
        make_fault_samples(
            fault_sensor=sensor,
            sensors=_4_SENSORS,
            speed_kmh=80.0,
            n_samples=30,
            start_t_s=20,
            fault_amp=0.07,
            fault_vib_db=28.0,
        )
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    assert top is not None, f"Phased 4sensor lost {corner}"
    assert_wheel_source(summary, msg=f"phased 4s {corner}")
    assert_strongest_location(summary, sensor, msg=f"phased 4s {corner}")


# ---------------------------------------------------------------------------
# D.10 – 8-sensor no-fault baseline (1 case)
# ---------------------------------------------------------------------------


def test_8sensor_no_fault_baseline() -> None:
    """8 sensors, all noise → no wheel fault."""
    samples = make_noise_samples(sensors=_8_SENSORS, speed_kmh=SPEED_MID, n_samples=40)
    summary = run_analysis(samples)
    assert_no_wheel_fault(summary, msg="8sensor-no-fault")


# ---------------------------------------------------------------------------
# D.11 – 12-sensor no-fault baseline (1 case)
# ---------------------------------------------------------------------------


def test_12sensor_no_fault_baseline() -> None:
    """12 sensors, all noise → no wheel fault."""
    samples = make_noise_samples(sensors=_12_SENSORS, speed_kmh=SPEED_MID, n_samples=40)
    summary = run_analysis(samples)
    assert_no_wheel_fault(summary, msg="12sensor-no-fault")


# ---------------------------------------------------------------------------
# D.12 – Diffuse on 8 and 12 sensors (2 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sensors,label",
    [(_8_SENSORS, "8s"), (_12_SENSORS, "12s")],
    ids=["8s_diffuse", "12s_diffuse"],
)
def test_multi_sensor_diffuse_no_fault(sensors: list[str], label: str) -> None:
    """Diffuse excitation across many sensors → no localized fault."""
    samples = make_diffuse_samples(sensors=sensors, speed_kmh=SPEED_HIGH, n_samples=35)
    summary = run_analysis(samples)
    assert_no_wheel_fault(summary, msg=label)


# ---------------------------------------------------------------------------
# D.13 – Speed sweep with 4 sensors (2 corners = 2 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corner", ["FR", "RL"])
def test_4sensor_speed_sweep(corner: str) -> None:
    """Speed sweep with fault at one corner on 4 sensors."""
    from builders import make_speed_sweep_fault_samples

    sensor = CORNER_SENSORS[corner]
    samples = make_speed_sweep_fault_samples(
        fault_sensor=sensor,
        sensors=_4_SENSORS,
        speed_start=40,
        speed_end=100,
        n_steps=5,
        samples_per_step=8,
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    assert top is not None, f"No finding for 4sensor sweep {corner}"
    assert_wheel_source(summary, msg=f"sweep 4s {corner}")
    assert_strongest_location(summary, CORNER_SENSORS[corner], msg=f"sweep 4s {corner}")


# ---------------------------------------------------------------------------
# D.14 – Weak signal multi-sensor (2 corners = 2 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corner", ["FL", "RR"])
def test_4sensor_weak_signal(corner: str) -> None:
    """Weak fault on 4 sensors → low or no confidence."""
    sensor = CORNER_SENSORS[corner]
    samples = make_fault_samples(
        fault_sensor=sensor,
        sensors=_4_SENSORS,
        speed_kmh=SPEED_MID,
        n_samples=40,
        fault_amp=0.008,
        noise_amp=0.005,
        fault_vib_db=12.0,
        noise_vib_db=10.0,
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    if top:
        conf = float(top.get("confidence", 0))
        assert conf < 0.90, f"Weak signal → unexpectedly high conf={conf} for {corner}"


# ---------------------------------------------------------------------------
# D.15 – Very high speed 4-sensor (4 corners = 4 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corner", _CORNERS)
def test_4sensor_very_high_speed(corner: str) -> None:
    """4-sensor fault at 120 km/h."""
    sensor = CORNER_SENSORS[corner]
    samples = make_fault_samples(
        fault_sensor=sensor,
        sensors=_4_SENSORS,
        speed_kmh=SPEED_VERY_HIGH,
        n_samples=35,
        fault_amp=0.08,
        fault_vib_db=30.0,
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    assert top is not None, f"No finding for 4sensor {corner}@120"
    assert_wheel_source(summary, msg=f"4s {corner}@120")
    assert_strongest_location(summary, sensor, msg=f"4s {corner}@120")
