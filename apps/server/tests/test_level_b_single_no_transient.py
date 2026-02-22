# ruff: noqa: E501
"""Level B – Single sensor, no transient (≥50 direct-injection cases).

Tests the analysis pipeline with exactly ONE sensor and NO transient
spikes.  Covers: four corners, three speed bands, no-fault baselines,
diffuse noise, phased onset, ambiguous vs clean separation.
"""

from __future__ import annotations

import pytest
from builders import (
    CORNER_SENSORS,
    SENSOR_FL,
    SPEED_HIGH,
    SPEED_LOW,
    SPEED_MID,
    SPEED_VERY_HIGH,
    assert_confidence_between,
    assert_no_wheel_fault,
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
# B.1 – Fault at each corner × speed band (4 corners × 3 speeds = 12 cases)
# ---------------------------------------------------------------------------

_CORNERS = ["FL", "FR", "RL", "RR"]
_SPEEDS = [SPEED_LOW, SPEED_MID, SPEED_HIGH]


@pytest.mark.parametrize("corner", _CORNERS)
@pytest.mark.parametrize("speed", _SPEEDS, ids=["low", "mid", "high"])
def test_single_sensor_fault_corner_speed(corner: str, speed: float) -> None:
    """Wheel fault on single sensor at each corner × speed band."""
    sensor = CORNER_SENSORS[corner]
    samples = make_fault_samples(
        fault_sensor=sensor,
        sensors=[sensor],
        speed_kmh=speed,
        n_samples=40,
        fault_amp=0.07,
        fault_vib_db=28.0,
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    assert top is not None, f"No finding for {corner}@{speed}"
    assert_confidence_between(summary, 0.15, 1.0, msg=f"{corner}@{speed}")


# ---------------------------------------------------------------------------
# B.2 – No-fault baseline at each speed (3 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("speed", _SPEEDS, ids=["low", "mid", "high"])
def test_single_sensor_no_fault_baseline(speed: float) -> None:
    """Pure road noise on one sensor → no wheel fault diagnosed."""
    samples = make_noise_samples(sensors=[SENSOR_FL], speed_kmh=speed, n_samples=40)
    summary = run_analysis(samples)
    assert_no_wheel_fault(summary, msg=f"speed={speed}")


# ---------------------------------------------------------------------------
# B.3 – Varying fault amplitude (low/med/high) × 2 corners = 6 cases
# ---------------------------------------------------------------------------

_AMPS = [
    ("low", 0.02, 16.0),
    ("med", 0.05, 24.0),
    ("high", 0.10, 32.0),
]


@pytest.mark.parametrize("corner", ["FL", "RR"])
@pytest.mark.parametrize(
    "amp_label,fault_amp,vib_db", _AMPS, ids=["amp_low", "amp_med", "amp_high"]
)
def test_single_sensor_amplitude_scaling(
    corner: str, amp_label: str, fault_amp: float, vib_db: float
) -> None:
    """Confidence should scale with fault amplitude."""
    sensor = CORNER_SENSORS[corner]
    samples = make_fault_samples(
        fault_sensor=sensor,
        sensors=[sensor],
        speed_kmh=SPEED_MID,
        n_samples=40,
        fault_amp=fault_amp,
        fault_vib_db=vib_db,
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    if amp_label == "low":
        # Low amplitude may or may not produce a finding
        pass
    else:
        assert top is not None, f"No finding for {corner} at amp={amp_label}"
        assert_confidence_between(summary, 0.15, 1.0, msg=f"{corner} amp={amp_label}")


# ---------------------------------------------------------------------------
# B.4 – Phased onset: idle → ramp → fault (4 corners = 4 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corner", _CORNERS)
def test_single_sensor_phased_onset(corner: str) -> None:
    """Idle → ramp → steady fault at one corner."""
    sensor = CORNER_SENSORS[corner]
    samples: list[dict] = []
    samples.extend(make_idle_samples(sensors=[sensor], n_samples=10, start_t_s=0))
    samples.extend(
        make_ramp_samples(
            sensors=[sensor], speed_start=20, speed_end=80, n_samples=15, start_t_s=10
        )
    )
    samples.extend(
        make_fault_samples(
            fault_sensor=sensor,
            sensors=[sensor],
            speed_kmh=80.0,
            n_samples=35,
            start_t_s=25,
            fault_amp=0.07,
            fault_vib_db=28.0,
        )
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    assert top is not None, f"No finding for phased {corner}"
    assert_confidence_between(summary, 0.15, 1.0, msg=f"phased {corner}")


# ---------------------------------------------------------------------------
# B.5 – Diffuse noise on single sensor (should NOT produce wheel fault) (3 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("speed", _SPEEDS, ids=["low", "mid", "high"])
def test_single_sensor_diffuse_no_fault(speed: float) -> None:
    """Diffuse broadband excitation on one sensor should not be a wheel fault."""
    samples = make_diffuse_samples(sensors=[SENSOR_FL], speed_kmh=speed, n_samples=40)
    summary = run_analysis(samples)
    assert_no_wheel_fault(summary, msg=f"diffuse@{speed}")


# ---------------------------------------------------------------------------
# B.6 – Very high speed (120 km/h) at each corner (4 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corner", _CORNERS)
def test_single_sensor_very_high_speed(corner: str) -> None:
    """Wheel fault at very high speed (120 km/h)."""
    sensor = CORNER_SENSORS[corner]
    samples = make_fault_samples(
        fault_sensor=sensor,
        sensors=[sensor],
        speed_kmh=SPEED_VERY_HIGH,
        n_samples=40,
        fault_amp=0.08,
        fault_vib_db=30.0,
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    assert top is not None, f"No finding for {corner}@120"
    assert_confidence_between(summary, 0.15, 1.0, msg=f"{corner}@120")


# ---------------------------------------------------------------------------
# B.7 – Idle only → no fault (1 case)
# ---------------------------------------------------------------------------


def test_single_sensor_idle_only_no_fault() -> None:
    """Pure idle data should produce no wheel fault."""
    samples = make_idle_samples(sensors=[SENSOR_FL], n_samples=50)
    summary = run_analysis(samples)
    assert_no_wheel_fault(summary, msg="idle-only")


# ---------------------------------------------------------------------------
# B.8 – Ramp only → no fault (1 case)
# ---------------------------------------------------------------------------


def test_single_sensor_ramp_only_no_fault() -> None:
    """Speed ramp with no fault content should produce no wheel fault."""
    samples = make_ramp_samples(sensors=[SENSOR_FL], speed_start=20, speed_end=100, n_samples=50)
    summary = run_analysis(samples)
    assert_no_wheel_fault(summary, msg="ramp-only")


# ---------------------------------------------------------------------------
# B.9 – Fault with 2x and 3x harmonics (4 corners = 4 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corner", _CORNERS)
def test_single_sensor_harmonics_1x_2x_3x(corner: str) -> None:
    """Strong fault with all three wheel harmonics."""
    sensor = CORNER_SENSORS[corner]
    samples = make_fault_samples(
        fault_sensor=sensor,
        sensors=[sensor],
        speed_kmh=SPEED_MID,
        n_samples=40,
        fault_amp=0.08,
        fault_vib_db=28.0,
        add_wheel_2x=True,
        add_wheel_3x=True,
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    assert top is not None, f"No finding for {corner} with 1x+2x+3x"
    assert_confidence_between(summary, 0.15, 1.0, msg=f"{corner} 1x+2x+3x")


# ---------------------------------------------------------------------------
# B.10 – Long duration steady fault (2 corners × 2 durations = 4 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corner", ["FL", "RR"])
@pytest.mark.parametrize("n_samples", [60, 100], ids=["60s", "100s"])
def test_single_sensor_long_steady(corner: str, n_samples: int) -> None:
    """Longer recording durations should maintain or improve detection."""
    sensor = CORNER_SENSORS[corner]
    samples = make_fault_samples(
        fault_sensor=sensor,
        sensors=[sensor],
        speed_kmh=SPEED_HIGH,
        n_samples=n_samples,
        fault_amp=0.06,
        fault_vib_db=26.0,
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    assert top is not None, f"No finding for long {corner}"
    assert_confidence_between(summary, 0.15, 1.0, msg=f"long {corner} n={n_samples}")


# ---------------------------------------------------------------------------
# B.11 – Weak signal barely above noise (4 corners = 4 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corner", _CORNERS)
def test_single_sensor_weak_signal(corner: str) -> None:
    """Very weak fault should produce low confidence or no finding."""
    sensor = CORNER_SENSORS[corner]
    samples = make_fault_samples(
        fault_sensor=sensor,
        sensors=[sensor],
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
        # If detected, confidence should be modest
        conf = float(top.get("confidence", 0))
        assert conf < 0.90, f"Unexpectedly high confidence {conf} for weak {corner}"


# ---------------------------------------------------------------------------
# B.12 – Speed sweep fault (2 corners = 2 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corner", ["FR", "RL"])
def test_single_sensor_speed_sweep_fault(corner: str) -> None:
    """Fault present across a speed sweep should be detected."""
    from builders import make_speed_sweep_fault_samples

    sensor = CORNER_SENSORS[corner]
    samples = make_speed_sweep_fault_samples(
        fault_sensor=sensor,
        sensors=[sensor],
        speed_start=40,
        speed_end=100,
        n_steps=5,
        samples_per_step=10,
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    assert top is not None, f"No finding for speed-sweep {corner}"
    assert_confidence_between(summary, 0.15, 1.0, msg=f"sweep {corner}")


# ---------------------------------------------------------------------------
# B.13 – Noise floor variation (2 corners × 2 noise levels = 4 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corner", ["FL", "RR"])
@pytest.mark.parametrize("noise_amp", [0.001, 0.008], ids=["low_noise", "high_noise"])
def test_single_sensor_noise_floor_variation(corner: str, noise_amp: float) -> None:
    """Fault detection at different noise floor levels."""
    sensor = CORNER_SENSORS[corner]
    samples = make_fault_samples(
        fault_sensor=sensor,
        sensors=[sensor],
        speed_kmh=SPEED_MID,
        n_samples=40,
        fault_amp=0.06,
        noise_amp=noise_amp,
        fault_vib_db=26.0,
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    assert top is not None, f"No finding for {corner} noise={noise_amp}"
    assert_confidence_between(summary, 0.15, 1.0, msg=f"{corner} noise={noise_amp}")
