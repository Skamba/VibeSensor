"""Opt-in single-sensor synthetic diagnostic matrix.

Representative corner/speed, no-fault baseline, and phased-onset coverage now
lives in ``test_synthetic_scenario_matrix.py``. This module keeps the
single-sensor-specific behavior axes available outside default backend CI.
"""

from __future__ import annotations

from typing import Any

import pytest
from test_support import (
    CAR_PROFILES,
    CORNER_SENSORS,
    SENSOR_FL,
    SPEED_HIGH,
    SPEED_LOW,
    SPEED_MID,
    SPEED_VERY_HIGH,
    assert_confidence_between,
    assert_confidence_label_valid,
    assert_pairwise_monotonic,
    assert_strict_no_fault,
    assert_tolerant_no_fault,
    extract_top,
    make_diffuse_samples,
    make_idle_samples,
    make_profile_fault_samples,
    make_profile_speed_sweep_fault_samples,
    make_ramp_samples,
    profile_metadata,
    run_analysis,
)

pytestmark = pytest.mark.diagnostic_matrix

_CORNERS = ["FL", "FR", "RL", "RR"]
_SPEEDS = [SPEED_LOW, SPEED_MID, SPEED_HIGH]
# Keep profile coverage broad with a light matrix: first/middle/last profile.
_OPTIMIZED_CAR_PROFILES = [CAR_PROFILES[0], CAR_PROFILES[2], CAR_PROFILES[-1]]
_OPTIMIZED_CAR_PROFILE_IDS = [p["name"] for p in _OPTIMIZED_CAR_PROFILES]


# Shared helper: run single-sensor fault analysis


def _run_single_fault(
    profile: dict[str, Any],
    corner: str,
    *,
    speed_kmh: float = SPEED_MID,
    n_samples: int = 40,
    fault_amp: float = 0.07,
    fault_vib_db: float = 28.0,
    noise_amp: float | None = None,
    noise_vib_db: float | None = None,
    add_wheel_2x: bool = False,
    start_t_s: float | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Create single-sensor fault samples, run analysis, return (summary, top)."""
    sensor = CORNER_SENSORS[corner]
    kwargs: dict[str, Any] = {
        "profile": profile,
        "fault_sensor": sensor,
        "sensors": [sensor],
        "speed_kmh": speed_kmh,
        "n_samples": n_samples,
        "fault_amp": fault_amp,
        "fault_vib_db": fault_vib_db,
    }
    if noise_amp is not None:
        kwargs["noise_amp"] = noise_amp
    if noise_vib_db is not None:
        kwargs["noise_vib_db"] = noise_vib_db
    if add_wheel_2x:
        kwargs["add_wheel_2x"] = True
    if start_t_s is not None:
        kwargs["start_t_s"] = start_t_s
    samples = make_profile_fault_samples(**kwargs)
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    return summary, extract_top(summary)


# B.3 – Varying fault amplitude (low/med/high) × 2 corners = 6 cases

_AMPS = [
    ("low", 0.02, 16.0),
    ("med", 0.05, 24.0),
    ("high", 0.10, 32.0),
]


@pytest.mark.parametrize("profile", _OPTIMIZED_CAR_PROFILES, ids=_OPTIMIZED_CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", ["FL", "RR"])
@pytest.mark.parametrize(
    ("amp_label", "fault_amp", "vib_db"),
    _AMPS,
    ids=["amp_low", "amp_med", "amp_high"],
)
def test_single_sensor_amplitude_scaling(
    corner: str,
    amp_label: str,
    fault_amp: float,
    vib_db: float,
    profile: dict[str, Any],
) -> None:
    """Confidence should scale with fault amplitude."""
    summary, top = _run_single_fault(profile, corner, fault_amp=fault_amp, fault_vib_db=vib_db)
    if amp_label == "low":
        assert_tolerant_no_fault(
            summary,
            msg=f"Low amplitude should not produce a confident wheel fault at {corner}",
        )
    else:
        assert top is not None, f"No finding for {corner} at amp={amp_label}"
        min_conf = 0.20 if amp_label == "med" else 0.25
        assert_confidence_between(summary, min_conf, 1.0, msg=f"{corner} amp={amp_label}")


@pytest.mark.parametrize("profile", _OPTIMIZED_CAR_PROFILES, ids=_OPTIMIZED_CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", ["FL", "RR"])
def test_single_sensor_amplitude_scaling_monotonic(corner: str, profile: dict[str, Any]) -> None:
    """Confidence should increase with amplitude (allowing tiny tolerated regressions)."""
    monotonic_tiers = [
        ("low", 0.02, 16.0),
        ("med", 0.05, 24.0),
        ("strong", 0.07, 28.0),
    ]
    confidences: list[float] = []
    labels: list[str] = []
    for amp_label, fault_amp, vib_db in monotonic_tiers:
        summary, top = _run_single_fault(
            profile,
            corner,
            fault_amp=fault_amp,
            fault_vib_db=vib_db,
        )
        confidences.append(float(top.get("confidence", 0.0)) if top else 0.0)
        labels.append(amp_label)
    assert_pairwise_monotonic(
        confidences,
        tolerance=0.03,
        labels=labels,
        msg=f"single-sensor amplitude scaling at {corner} ({profile['name']})",
    )


# B.5 – Diffuse noise on single sensor (should NOT produce wheel fault) (3 cases)


@pytest.mark.parametrize("profile", _OPTIMIZED_CAR_PROFILES, ids=_OPTIMIZED_CAR_PROFILE_IDS)
@pytest.mark.parametrize("speed", _SPEEDS, ids=["low", "mid", "high"])
def test_single_sensor_diffuse_no_fault(speed: float, profile: dict[str, Any]) -> None:
    """Diffuse broadband excitation on one sensor should not be a wheel fault."""
    samples = make_diffuse_samples(sensors=[SENSOR_FL], speed_kmh=speed, n_samples=40)
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    assert_tolerant_no_fault(summary, msg=f"diffuse@{speed}")


# B.6 – Very high speed (120 km/h) at each corner (4 cases)


@pytest.mark.parametrize("profile", _OPTIMIZED_CAR_PROFILES, ids=_OPTIMIZED_CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", _CORNERS)
def test_single_sensor_very_high_speed(corner: str, profile: dict[str, Any]) -> None:
    """Wheel fault at very high speed (120 km/h)."""
    summary, top = _run_single_fault(
        profile,
        corner,
        speed_kmh=SPEED_VERY_HIGH,
        fault_amp=0.08,
        fault_vib_db=30.0,
    )
    assert top is not None, f"No finding for {corner}@120"
    assert_confidence_between(summary, 0.15, 1.0, msg=f"{corner}@120")
    assert_confidence_label_valid(summary, msg=f"{corner}@120")


# B.7 – Idle only → no fault (1 case)


@pytest.mark.parametrize("profile", _OPTIMIZED_CAR_PROFILES, ids=_OPTIMIZED_CAR_PROFILE_IDS)
def test_single_sensor_idle_only_no_fault(profile: dict[str, Any]) -> None:
    """Pure idle data should produce no wheel fault."""
    samples = make_idle_samples(sensors=[SENSOR_FL], n_samples=50)
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    assert_strict_no_fault(summary, msg="idle-only")


# B.8 – Ramp only → no fault (1 case)


@pytest.mark.parametrize("profile", _OPTIMIZED_CAR_PROFILES, ids=_OPTIMIZED_CAR_PROFILE_IDS)
def test_single_sensor_ramp_only_no_fault(profile: dict[str, Any]) -> None:
    """Speed ramp with no fault content should produce no wheel fault."""
    samples = make_ramp_samples(sensors=[SENSOR_FL], speed_start=20, speed_end=100, n_samples=50)
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    assert_strict_no_fault(summary, msg="ramp-only")


# B.9 – Fault with 1x and 2x harmonics (4 corners = 4 cases)


@pytest.mark.parametrize("profile", _OPTIMIZED_CAR_PROFILES, ids=_OPTIMIZED_CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", _CORNERS)
def test_single_sensor_harmonics_1x_2x(corner: str, profile: dict[str, Any]) -> None:
    """Strong fault with primary and second wheel harmonics."""
    summary, top = _run_single_fault(
        profile,
        corner,
        fault_amp=0.08,
        add_wheel_2x=True,
    )
    assert top is not None, f"No finding for {corner} with 1x+2x"
    assert_confidence_between(summary, 0.15, 1.0, msg=f"{corner} 1x+2x")
    assert_confidence_label_valid(summary, msg=f"{corner} 1x+2x")


# B.10 – Long duration steady fault (2 corners × 2 durations = 4 cases)


@pytest.mark.parametrize("profile", _OPTIMIZED_CAR_PROFILES, ids=_OPTIMIZED_CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", ["FL", "RR"])
@pytest.mark.parametrize("n_samples", [60, 100], ids=["60s", "100s"])
def test_single_sensor_long_steady(corner: str, n_samples: int, profile: dict[str, Any]) -> None:
    """Longer recording durations should maintain or improve detection."""
    summary, top = _run_single_fault(
        profile,
        corner,
        speed_kmh=SPEED_HIGH,
        n_samples=n_samples,
        fault_amp=0.06,
        fault_vib_db=26.0,
    )
    assert top is not None, f"No finding for long {corner}"
    assert_confidence_between(summary, 0.15, 1.0, msg=f"long {corner} n={n_samples}")


# B.11 – Weak signal barely above noise (4 corners = 4 cases)


@pytest.mark.parametrize("profile", _OPTIMIZED_CAR_PROFILES, ids=_OPTIMIZED_CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", _CORNERS)
def test_single_sensor_weak_signal(corner: str, profile: dict[str, Any]) -> None:
    """Very weak fault should produce low confidence or no finding."""
    summary, top = _run_single_fault(
        profile,
        corner,
        fault_amp=0.008,
        noise_amp=0.005,
        fault_vib_db=12.0,
        noise_vib_db=10.0,
    )
    assert summary, f"Expected non-empty summary for weak {corner}"
    if top:
        # If detected, confidence should be modest
        conf = float(top.get("confidence", 0))
        assert conf < 0.90, f"Unexpectedly high confidence {conf} for weak {corner}"
    else:
        assert_tolerant_no_fault(
            summary,
            msg=f"Weak {corner} should not produce high-confidence wheel fault",
        )


# B.12 – Speed sweep fault (2 corners = 2 cases)


@pytest.mark.parametrize("profile", _OPTIMIZED_CAR_PROFILES, ids=_OPTIMIZED_CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", ["FR", "RL"])
def test_single_sensor_speed_sweep_fault(corner: str, profile: dict[str, Any]) -> None:
    """Fault present across a speed sweep should be detected."""
    sensor = CORNER_SENSORS[corner]
    samples = make_profile_speed_sweep_fault_samples(
        profile=profile,
        fault_sensor=sensor,
        sensors=[sensor],
        speed_start=40,
        speed_end=100,
        n_steps=5,
        samples_per_step=10,
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    top = extract_top(summary)
    assert top is not None, f"No finding for speed-sweep {corner}"
    assert_confidence_between(summary, 0.15, 1.0, msg=f"sweep {corner}")


# B.13 – Noise floor variation (2 corners × 2 noise levels = 4 cases)


@pytest.mark.parametrize("profile", _OPTIMIZED_CAR_PROFILES, ids=_OPTIMIZED_CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", ["FL", "RR"])
@pytest.mark.parametrize("noise_amp", [0.001, 0.008], ids=["low_noise", "high_noise"])
def test_single_sensor_noise_floor_variation(
    corner: str,
    noise_amp: float,
    profile: dict[str, Any],
) -> None:
    """Fault detection at different noise floor levels."""
    summary, top = _run_single_fault(
        profile,
        corner,
        fault_amp=0.06,
        noise_amp=noise_amp,
        fault_vib_db=26.0,
    )
    assert top is not None, f"No finding for {corner} noise={noise_amp}"
    assert_confidence_between(summary, 0.15, 1.0, msg=f"{corner} noise={noise_amp}")
