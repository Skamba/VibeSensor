# ruff: noqa: E501
"""Car profile variation tests (≥50 direct-injection cases).

Validates that the analysis pipeline correctly detects faults across
different vehicle configurations: tire sizes, gear ratios, final drive
ratios, and sensor layouts.  The same wheel-order fault injected with
the correct wheel Hz for each profile must be detected regardless of
the vehicle parameters — this catches hard-coded frequency assumptions.

Uses the five shared profiles from ``builders.CAR_PROFILES``.
"""

from __future__ import annotations

from typing import Any

import pytest
from builders import (
    ALL_WHEEL_SENSORS,
    CAR_PROFILE_IDS,
    CAR_PROFILES,
    CORNER_SENSORS,
    SENSOR_FL,
    SPEED_HIGH,
    SPEED_LOW,
    SPEED_MID,
    assert_confidence_label_valid,
    assert_no_wheel_fault,
    make_noise_samples,
    make_profile_fault_samples,
    profile_circ,
    profile_metadata,
    profile_wheel_hz,
    run_analysis,
    top_confidence,
)

_CORNERS = ["FL", "FR", "RL", "RR"]


def _profile_engine_hz(profile: dict[str, Any], speed_kmh: float) -> float:
    """Compute engine-1x Hz for a profile at a given speed."""
    whz = profile_wheel_hz(profile, speed_kmh)
    return whz * profile["final_drive_ratio"] * profile["current_gear_ratio"]


# ===================================================================
# P1 – Fault detection across car profiles
# 5 profiles × 4 corners = 20 cases
# ===================================================================
@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", _CORNERS)
def test_fault_detected_across_profiles(profile: dict[str, Any], corner: str) -> None:
    """Wheel fault must be detected with correct profile-specific wheel Hz."""
    sensor = CORNER_SENSORS[corner]
    samples = make_profile_fault_samples(
        profile=profile,
        fault_sensor=sensor,
        sensors=[sensor],
        speed_kmh=SPEED_MID,
    )
    meta = profile_metadata(profile)
    summary = run_analysis(samples, metadata=meta)
    conf = top_confidence(summary)
    assert conf >= 0.25, (
        f"Fault not detected for profile={profile['name']}, corner={corner}: conf={conf:.3f}"
    )
    assert_confidence_label_valid(summary)


# ===================================================================
# P2 – No-fault baseline across profiles: pure noise should not trigger
# 5 profiles × 2 speeds = 10 cases
# ===================================================================
@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize("speed", [SPEED_MID, SPEED_HIGH], ids=["mid", "high"])
def test_nofault_baseline_across_profiles(profile: dict[str, Any], speed: float) -> None:
    """Pure noise with any car profile should not produce a wheel fault."""
    samples = make_noise_samples(sensors=ALL_WHEEL_SENSORS, speed_kmh=speed, n_samples=35)
    meta = profile_metadata(profile)
    summary = run_analysis(samples, metadata=meta)
    assert_no_wheel_fault(summary, msg=f"profile={profile['name']} speed={speed}")


# ===================================================================
# P3 – Fault detection at different speeds per profile
# 5 profiles × 3 speeds = 15 cases
# ===================================================================
@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize("speed", [SPEED_LOW, SPEED_MID, SPEED_HIGH], ids=["low", "mid", "high"])
def test_fault_across_speeds_and_profiles(profile: dict[str, Any], speed: float) -> None:
    """Fault detection must work across different speed bands for each profile."""
    samples = make_profile_fault_samples(
        profile=profile,
        fault_sensor=SENSOR_FL,
        sensors=[SENSOR_FL],
        speed_kmh=speed,
    )
    meta = profile_metadata(profile)
    summary = run_analysis(samples, metadata=meta)
    conf = top_confidence(summary)
    assert conf >= 0.25, (
        f"Fault not detected: profile={profile['name']}, speed={speed}: conf={conf:.3f}"
    )


# ===================================================================
# P4 – Wrong profile: analysis stays robust with mismatched metadata
# 5 profiles = 5 cases
# ===================================================================
@pytest.mark.parametrize("profile_idx", range(len(CAR_PROFILES)), ids=CAR_PROFILE_IDS)
def test_wrong_profile_analysis_robust(profile_idx: int) -> None:
    """Analysis with wrong car profile should still produce a valid, non-crashing result."""
    correct_profile = CAR_PROFILES[profile_idx]
    wrong_profile = CAR_PROFILES[(profile_idx + 1) % len(CAR_PROFILES)]

    samples = make_profile_fault_samples(
        profile=correct_profile,
        fault_sensor=SENSOR_FL,
        sensors=[SENSOR_FL],
        speed_kmh=SPEED_MID,
    )

    # Analyze with wrong metadata — should not crash
    meta_wrong = profile_metadata(wrong_profile)
    summary_wrong = run_analysis(samples, metadata=meta_wrong)
    assert "top_causes" in summary_wrong
    assert "warnings" in summary_wrong

    # Correct metadata should work
    meta_correct = profile_metadata(correct_profile)
    summary_correct = run_analysis(samples, metadata=meta_correct)
    conf_correct = top_confidence(summary_correct)
    assert conf_correct >= 0.25, (
        f"Correct profile should detect fault: profile={correct_profile['name']}"
    )


# ===================================================================
# P5 – Wheel Hz sanity: each profile produces plausible frequencies
# 5 profiles = 5 cases
# ===================================================================
@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
def test_wheel_hz_sanity(profile: dict[str, Any]) -> None:
    """Each profile's tire circumference produces a reasonable wheel Hz."""
    circ = profile_circ(profile)
    assert 1.5 < circ < 3.5, f"Tire circumference {circ:.3f}m out of expected range"

    for speed in [30.0, 60.0, 100.0, 120.0]:
        whz = profile_wheel_hz(profile, speed)
        assert 3.0 < whz < 25.0, (
            f"wheel_hz={whz:.2f} at {speed} km/h out of expected range "
            f"for profile={profile['name']}"
        )

    ehz = _profile_engine_hz(profile, 80.0)
    whz = profile_wheel_hz(profile, 80.0)
    assert ehz > whz, f"Engine Hz ({ehz:.2f}) should exceed wheel Hz ({whz:.2f})"
