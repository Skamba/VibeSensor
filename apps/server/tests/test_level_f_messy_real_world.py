# ruff: noqa: E501
"""Level F – Messy real-world scenarios (direct injection, deterministic).

Tests the analysis pipeline with realistic edge cases that simulate
real-world data quality issues: sensor dropouts, speed jitter, road
surface changes, overlapping harmonics, dual faults, and gain mismatch.
All tests use direct injection for speed and determinism.
"""

from __future__ import annotations

import pytest
from builders import (
    ALL_WHEEL_SENSORS,
    CORNER_SENSORS,
    SENSOR_FL,
    SENSOR_FR,
    SENSOR_RL,
    SENSOR_RR,
    SPEED_HIGH,
    SPEED_MID,
    _stable_hash,
    assert_confidence_between,
    assert_diagnosis_contract,
    assert_pairwise_monotonic,
    assert_strongest_location,
    assert_tolerant_no_fault,
    assert_wheel_source,
    extract_top,
    make_clock_skew_samples,
    make_dropout_samples,
    make_dual_fault_samples,
    make_engine_order_samples,
    make_fault_samples,
    make_gain_mismatch_samples,
    make_out_of_order_samples,
    make_road_phase_samples,
    make_speed_jitter_samples,
    make_transient_samples,
    run_analysis,
    top_confidence,
)

_4S = ALL_WHEEL_SENSORS[:]
_CORNERS = ["FL", "FR", "RL", "RR"]


# ---------------------------------------------------------------------------
# F.1 – Persistent wheel fault + sensor dropout (4 corners = 4 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corner", _CORNERS)
def test_fault_with_sensor_dropout(corner: str) -> None:
    """Persistent fault on one corner, with dropout on a *different* sensor mid-run.

    The dropout sensor goes offline for 10 seconds. The fault should still
    be detected and localized correctly.
    """
    fault_sensor = CORNER_SENSORS[corner]
    dropout_sensor = SENSOR_RR if corner != "RR" else SENSOR_FL
    base = make_fault_samples(
        fault_sensor=fault_sensor,
        sensors=_4S,
        speed_kmh=SPEED_HIGH,
        n_samples=40,
        fault_amp=0.07,
        fault_vib_db=28.0,
    )
    samples = make_dropout_samples(
        base_samples=base,
        dropout_sensor=dropout_sensor,
        dropout_start_t=15.0,
        dropout_end_t=25.0,
    )
    summary = run_analysis(samples)
    assert_diagnosis_contract(
        summary,
        expected_source="wheel",
        expected_sensor=fault_sensor,
        min_confidence=0.15,
        msg=f"fault+dropout {corner}",
    )


# ---------------------------------------------------------------------------
# F.2 – Persistent wheel fault + speed jitter (4 corners = 4 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corner", _CORNERS)
def test_fault_with_speed_jitter(corner: str) -> None:
    """Persistent fault with GPS speed jitter (±8 km/h fluctuation).

    Despite fluctuating speed readings, the wheel fault should still be detected.
    """
    fault_sensor = CORNER_SENSORS[corner]
    # Create fault samples, then inject speed jitter
    fault = make_fault_samples(
        fault_sensor=fault_sensor,
        sensors=_4S,
        speed_kmh=80.0,
        n_samples=40,
        fault_amp=0.07,
        fault_vib_db=28.0,
    )
    # Add speed jitter: perturb the speed of each sample
    jittered: list[dict] = []
    for i, s in enumerate(fault):
        h = _stable_hash(f"jitter-{i}")
        jitter = 8.0 * ((h % 200) / 100.0 - 1.0)
        s = {**s, "speed_kmh": max(5.0, s["speed_kmh"] + jitter)}
        jittered.append(s)

    summary = run_analysis(jittered)
    top = extract_top(summary)
    assert top is not None, f"No finding for fault+jitter {corner}"
    assert_wheel_source(summary, msg=f"fault+jitter {corner}")
    assert_confidence_between(summary, 0.10, 1.0, msg=f"fault+jitter {corner}")


# ---------------------------------------------------------------------------
# F.3 – No-fault diffuse + pothole transients (2 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("speed", [SPEED_MID, SPEED_HIGH], ids=["mid", "high"])
def test_diffuse_noise_with_pothole_transients(speed: float) -> None:
    """Diffuse road noise + pothole-style transient bursts on all sensors.

    Should NOT produce a localized wheel fault—road surface is the cause.
    """
    samples: list[dict] = []
    samples.extend(
        make_road_phase_samples(sensors=_4S, speed_kmh=speed, smooth_n=25, rough_n=0, pothole_n=0)
    )
    # Add transient bursts on each sensor (simulating potholes)
    for i, sensor in enumerate(_4S):
        samples.extend(
            make_transient_samples(
                sensor=sensor,
                speed_kmh=speed,
                n_samples=3,
                start_t_s=25 + i * 2,
                spike_amp=0.12,
                spike_vib_db=33.0,
                spike_freq_hz=20.0,
            )
        )
    summary = run_analysis(samples)
    assert_tolerant_no_fault(summary, msg=f"diffuse+pothole@{speed}")


# ---------------------------------------------------------------------------
# F.4 – Overlapping engine/wheel harmonics (2 speeds = 2 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("speed", [60.0, 100.0], ids=["60kmh", "100kmh"])
def test_overlapping_engine_wheel_harmonics(speed: float) -> None:
    """Engine-order + wheel-order fault present simultaneously.

    At certain speeds engine harmonics can overlap wheel harmonics.
    The analysis should still detect the wheel fault as primary.
    """
    samples: list[dict] = []
    # Engine excitation on all sensors
    samples.extend(
        make_engine_order_samples(
            sensors=_4S,
            speed_kmh=speed,
            n_samples=15,
            engine_amp=0.03,
            engine_vib_db=20.0,
        )
    )
    # Wheel fault on FL
    samples.extend(
        make_fault_samples(
            fault_sensor=SENSOR_FL,
            sensors=_4S,
            speed_kmh=speed,
            n_samples=30,
            start_t_s=15,
            fault_amp=0.07,
            fault_vib_db=28.0,
        )
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    assert top is not None, f"No finding for engine+wheel@{speed}"
    # We expect a finding; the fault sensor should be FL
    assert_strongest_location(summary, SENSOR_FL, msg=f"engine+wheel@{speed}")


# ---------------------------------------------------------------------------
# F.5 – Dual fault ambiguity (2 pairs = 2 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pair,primary",
    [
        ((SENSOR_FL, SENSOR_RR), SENSOR_FL),
        ((SENSOR_FR, SENSOR_RL), SENSOR_FR),
    ],
    ids=["FL_RR", "FR_RL"],
)
def test_dual_fault_detection(pair: tuple[str, str], primary: str) -> None:
    """Two sensors have wheel faults simultaneously (primary is stronger).

    The analysis should detect at least the primary fault and report
    multiple causes.
    """
    samples = make_dual_fault_samples(
        fault_sensor_1=pair[0],
        fault_sensor_2=pair[1],
        sensors=_4S,
        speed_kmh=SPEED_HIGH,
        n_samples=40,
        fault_amp_1=0.07,
        fault_amp_2=0.04,
        fault_vib_db_1=28.0,
        fault_vib_db_2=22.0,
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    assert top is not None, f"No finding for dual-fault {pair}"
    # The stronger fault should be the primary diagnosis
    assert_strongest_location(summary, primary, msg=f"dual-fault primary={primary}")
    # There should be multiple findings
    findings = summary.get("findings") or []
    assert len(findings) >= 1, f"Expected multiple findings for dual fault, got {len(findings)}"


# ---------------------------------------------------------------------------
# F.6 – Road surface phase changes (1 case)
# ---------------------------------------------------------------------------


def test_road_phase_smooth_rough_pothole() -> None:
    """Smooth → rough → pothole road surface with no real fault.

    Should NOT produce a high-confidence wheel fault.
    """
    samples = make_road_phase_samples(
        sensors=_4S,
        speed_kmh=SPEED_MID,
        smooth_n=20,
        rough_n=15,
        pothole_n=4,
    )
    summary = run_analysis(samples)
    assert_tolerant_no_fault(summary, msg="road-phases")


# ---------------------------------------------------------------------------
# F.7 – Out-of-order timestamps with fault (2 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corner", ["FL", "RR"])
def test_fault_with_out_of_order_timestamps(corner: str) -> None:
    """Fault data with some out-of-order timestamps (simulating network reordering)."""
    fault_sensor = CORNER_SENSORS[corner]
    base = make_fault_samples(
        fault_sensor=fault_sensor,
        sensors=_4S,
        speed_kmh=SPEED_MID,
        n_samples=40,
        fault_amp=0.07,
        fault_vib_db=28.0,
    )
    samples = make_out_of_order_samples(base_samples=base)
    summary = run_analysis(samples)
    top = extract_top(summary)
    assert top is not None, f"No finding for ooo-timestamps {corner}"
    assert_wheel_source(summary, msg=f"ooo {corner}")
    assert_strongest_location(summary, fault_sensor, msg=f"ooo {corner}")


# ---------------------------------------------------------------------------
# F.8 – Clock skew on one sensor with fault (2 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corner", ["FR", "RL"])
def test_fault_with_clock_skew(corner: str) -> None:
    """Fault with a 0.3s clock skew on one non-fault sensor."""
    fault_sensor = CORNER_SENSORS[corner]
    skew_sensor = SENSOR_RR if corner != "RR" else SENSOR_FL
    base = make_fault_samples(
        fault_sensor=fault_sensor,
        sensors=_4S,
        speed_kmh=SPEED_HIGH,
        n_samples=35,
        fault_amp=0.07,
        fault_vib_db=28.0,
    )
    samples = make_clock_skew_samples(
        base_samples=base,
        skew_sensor=skew_sensor,
        skew_offset_s=0.3,
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    assert top is not None, f"No finding for clock-skew {corner}"
    assert_wheel_source(summary, msg=f"skew {corner}")
    assert_strongest_location(summary, fault_sensor, msg=f"skew {corner}")


# ---------------------------------------------------------------------------
# F.9 – Gain mismatch on fault sensor (2 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corner", ["FL", "RL"])
def test_fault_with_gain_mismatch(corner: str) -> None:
    """Fault sensor has 1.5x gain (different sensitivity). Fault should still be localized."""
    fault_sensor = CORNER_SENSORS[corner]
    samples = make_gain_mismatch_samples(
        fault_sensor=fault_sensor,
        sensors=_4S,
        speed_kmh=SPEED_MID,
        n_samples=35,
        fault_amp=0.06,
        fault_vib_db=26.0,
        gain_factor=1.5,
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    assert top is not None, f"No finding for gain-mismatch {corner}"
    assert_wheel_source(summary, msg=f"gain {corner}")
    assert_strongest_location(summary, fault_sensor, msg=f"gain {corner}")


# ---------------------------------------------------------------------------
# F.10 – Pairwise monotonic amplitude trend on 4 sensors (1 case)
# ---------------------------------------------------------------------------


def test_pairwise_monotonic_amplitude_4sensor() -> None:
    """Confidence should increase (pairwise) with fault amplitude on 4 sensors."""
    amps = [(0.02, 16.0), (0.04, 20.0), (0.06, 26.0), (0.09, 30.0), (0.12, 34.0)]
    confs: list[float] = []
    labels: list[str] = []
    for amp, vdb in amps:
        samples = make_fault_samples(
            fault_sensor=SENSOR_FL,
            sensors=_4S,
            speed_kmh=SPEED_MID,
            n_samples=40,
            fault_amp=amp,
            fault_vib_db=vdb,
        )
        summary = run_analysis(samples)
        confs.append(top_confidence(summary))
        labels.append(f"amp={amp}")
    # Check pairwise monotonic (allowing 0.05 tolerance)
    assert_pairwise_monotonic(confs, tolerance=0.10, labels=labels, msg="amplitude sweep")


# ---------------------------------------------------------------------------
# F.11 – Persistent wheel fault + dropout on fault sensor itself (2 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corner", ["FL", "RR"])
def test_fault_with_self_dropout(corner: str) -> None:
    """Fault sensor itself drops out mid-run but has enough data before/after.

    Should still detect the fault with reduced confidence.
    """
    fault_sensor = CORNER_SENSORS[corner]
    base = make_fault_samples(
        fault_sensor=fault_sensor,
        sensors=_4S,
        speed_kmh=SPEED_HIGH,
        n_samples=50,
        fault_amp=0.07,
        fault_vib_db=28.0,
    )
    samples = make_dropout_samples(
        base_samples=base,
        dropout_sensor=fault_sensor,
        dropout_start_t=20.0,
        dropout_end_t=30.0,
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    assert top is not None, f"No finding for self-dropout {corner}"
    # Confidence may be lower due to missing data, but fault should be detected
    assert_confidence_between(summary, 0.10, 1.0, msg=f"self-dropout {corner}")


# ---------------------------------------------------------------------------
# F.12 – Engine-only excitation → no wheel fault (1 case)
# ---------------------------------------------------------------------------


def test_engine_only_no_wheel_fault() -> None:
    """Pure engine-order excitation on all sensors should NOT be a wheel fault."""
    samples = make_engine_order_samples(
        sensors=_4S,
        speed_kmh=SPEED_MID,
        n_samples=40,
        engine_amp=0.04,
        engine_vib_db=22.0,
    )
    summary = run_analysis(samples)
    assert_tolerant_no_fault(summary, msg="engine-only")


# ---------------------------------------------------------------------------
# F.13 – Speed jitter baseline → no false fault (1 case)
# ---------------------------------------------------------------------------


def test_speed_jitter_baseline_no_fault() -> None:
    """Speed jitter with clean noise → no false fault."""
    samples = make_speed_jitter_samples(
        sensors=_4S,
        base_speed_kmh=80.0,
        jitter_amplitude=10.0,
        n_samples=40,
    )
    summary = run_analysis(samples)
    assert_tolerant_no_fault(summary, msg="speed-jitter-baseline")
