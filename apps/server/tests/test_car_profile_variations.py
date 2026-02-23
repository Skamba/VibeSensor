# ruff: noqa: E501
"""Car profile variation tests (≥50 direct-injection cases).

Validates that the analysis pipeline correctly detects faults across
different vehicle configurations: tire sizes, gear ratios, final drive
ratios, and sensor layouts.  The same wheel-order fault injected with
the correct wheel Hz for each profile must be detected regardless of
the vehicle parameters — this catches hard-coded frequency assumptions.
"""

from __future__ import annotations

from typing import Any

import pytest
from builders import (
    ALL_WHEEL_SENSORS,
    CORNER_SENSORS,
    SENSOR_FL,
    SPEED_HIGH,
    SPEED_LOW,
    SPEED_MID,
    assert_confidence_label_valid,
    assert_no_wheel_fault,
    make_noise_samples,
    make_sample,
    run_analysis,
    standard_metadata,
    top_confidence,
)

from vibesensor.analysis_settings import (
    tire_circumference_m_from_spec,
    wheel_hz_from_speed_kmh,
)

# ---------------------------------------------------------------------------
# Car profiles: realistic combinations of tire size, drivetrain ratios
# ---------------------------------------------------------------------------

_PROFILES: list[dict[str, Any]] = [
    {
        "name": "performance_suv",
        "tire_width_mm": 285.0,
        "tire_aspect_pct": 30.0,
        "rim_in": 21.0,
        "final_drive_ratio": 3.08,
        "current_gear_ratio": 0.64,
    },
    {
        "name": "economy_sedan",
        "tire_width_mm": 205.0,
        "tire_aspect_pct": 55.0,
        "rim_in": 16.0,
        "final_drive_ratio": 3.94,
        "current_gear_ratio": 0.73,
    },
    {
        "name": "sports_coupe",
        "tire_width_mm": 225.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 18.0,
        "final_drive_ratio": 3.27,
        "current_gear_ratio": 0.85,
    },
    {
        "name": "off_road_truck",
        "tire_width_mm": 265.0,
        "tire_aspect_pct": 70.0,
        "rim_in": 17.0,
        "final_drive_ratio": 3.73,
        "current_gear_ratio": 0.75,
    },
    {
        "name": "compact_city",
        "tire_width_mm": 195.0,
        "tire_aspect_pct": 65.0,
        "rim_in": 15.0,
        "final_drive_ratio": 4.06,
        "current_gear_ratio": 0.68,
    },
]


def _profile_circ(profile: dict[str, Any]) -> float:
    """Compute tire circumference for a profile."""
    circ = tire_circumference_m_from_spec(
        profile["tire_width_mm"],
        profile["tire_aspect_pct"],
        profile["rim_in"],
    )
    assert circ is not None and circ > 0
    return circ


def _profile_wheel_hz(profile: dict[str, Any], speed_kmh: float) -> float:
    """Compute wheel Hz for a profile at a given speed."""
    circ = _profile_circ(profile)
    hz = wheel_hz_from_speed_kmh(speed_kmh, circ)
    assert hz is not None and hz > 0
    return hz


def _profile_engine_hz(profile: dict[str, Any], speed_kmh: float) -> float:
    """Compute engine-1x Hz for a profile at a given speed."""
    whz = _profile_wheel_hz(profile, speed_kmh)
    return whz * profile["final_drive_ratio"] * profile["current_gear_ratio"]


def _profile_metadata(profile: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """Build metadata dict for a specific car profile."""
    circ = _profile_circ(profile)
    meta = standard_metadata(
        tire_circumference_m=circ,
        final_drive_ratio=profile["final_drive_ratio"],
        current_gear_ratio=profile["current_gear_ratio"],
    )
    meta.update(overrides)
    return meta


def _make_profile_fault_samples(
    *,
    profile: dict[str, Any],
    fault_sensor: str,
    sensors: list[str],
    speed_kmh: float,
    fault_amp: float = 0.06,
    fault_vib_db: float = 26.0,
    noise_amp: float = 0.004,
    noise_vib_db: float = 8.0,
    n_samples: int = 30,
    add_wheel_2x: bool = True,
) -> list[dict[str, Any]]:
    """Generate wheel-order fault samples using the profile's wheel Hz."""
    whz = _profile_wheel_hz(profile, speed_kmh)
    samples: list[dict[str, Any]] = []
    for i in range(n_samples):
        t = float(i)
        for sensor in sensors:
            if sensor == fault_sensor:
                peaks: list[dict[str, float]] = [{"hz": whz, "amp": fault_amp}]
                if add_wheel_2x:
                    peaks.append({"hz": whz * 2, "amp": fault_amp * 0.4})
                peaks.append({"hz": 142.5, "amp": noise_amp})
                samples.append(
                    make_sample(
                        t_s=t,
                        speed_kmh=speed_kmh,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=fault_vib_db,
                        strength_floor_amp_g=noise_amp,
                    )
                )
            else:
                samples.append(
                    make_sample(
                        t_s=t,
                        speed_kmh=speed_kmh,
                        client_name=sensor,
                        top_peaks=[
                            {"hz": 142.5, "amp": noise_amp},
                            {"hz": 87.3, "amp": noise_amp * 0.8},
                        ],
                        vibration_strength_db=noise_vib_db,
                        strength_floor_amp_g=noise_amp,
                    )
                )
    return samples


_PROFILE_IDS = [p["name"] for p in _PROFILES]
_CORNERS = ["FL", "FR", "RL", "RR"]


# ===================================================================
# P1 – Fault detection across car profiles
# 5 profiles × 4 corners = 20 cases
# ===================================================================
@pytest.mark.parametrize("profile", _PROFILES, ids=_PROFILE_IDS)
@pytest.mark.parametrize("corner", _CORNERS)
def test_fault_detected_across_profiles(profile: dict[str, Any], corner: str) -> None:
    """Wheel fault must be detected with correct profile-specific wheel Hz."""
    sensor = CORNER_SENSORS[corner]
    samples = _make_profile_fault_samples(
        profile=profile,
        fault_sensor=sensor,
        sensors=[sensor],
        speed_kmh=SPEED_MID,
    )
    meta = _profile_metadata(profile)
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
@pytest.mark.parametrize("profile", _PROFILES, ids=_PROFILE_IDS)
@pytest.mark.parametrize("speed", [SPEED_MID, SPEED_HIGH], ids=["mid", "high"])
def test_nofault_baseline_across_profiles(profile: dict[str, Any], speed: float) -> None:
    """Pure noise with any car profile should not produce a wheel fault."""
    samples = make_noise_samples(sensors=ALL_WHEEL_SENSORS, speed_kmh=speed, n_samples=35)
    meta = _profile_metadata(profile)
    summary = run_analysis(samples, metadata=meta)
    assert_no_wheel_fault(summary, msg=f"profile={profile['name']} speed={speed}")


# ===================================================================
# P3 – Fault detection at different speeds per profile
# 5 profiles × 3 speeds = 15 cases
# ===================================================================
@pytest.mark.parametrize("profile", _PROFILES, ids=_PROFILE_IDS)
@pytest.mark.parametrize("speed", [SPEED_LOW, SPEED_MID, SPEED_HIGH], ids=["low", "mid", "high"])
def test_fault_across_speeds_and_profiles(profile: dict[str, Any], speed: float) -> None:
    """Fault detection must work across different speed bands for each profile."""
    samples = _make_profile_fault_samples(
        profile=profile,
        fault_sensor=SENSOR_FL,
        sensors=[SENSOR_FL],
        speed_kmh=speed,
    )
    meta = _profile_metadata(profile)
    summary = run_analysis(samples, metadata=meta)
    conf = top_confidence(summary)
    assert conf >= 0.25, (
        f"Fault not detected: profile={profile['name']}, speed={speed}: conf={conf:.3f}"
    )


# ===================================================================
# P4 – Wrong profile: using the wrong tire circumference produces
# a valid analysis (doesn't crash), but may change the source
# classification or confidence behaviour.
# 5 profiles = 5 cases (each tested against a different profile)
# ===================================================================
@pytest.mark.parametrize("profile_idx", range(len(_PROFILES)), ids=_PROFILE_IDS)
def test_wrong_profile_analysis_robust(profile_idx: int) -> None:
    """Analysis with wrong car profile should still produce a valid, non-crashing result."""
    correct_profile = _PROFILES[profile_idx]
    wrong_profile = _PROFILES[(profile_idx + 1) % len(_PROFILES)]

    # Generate fault with correct profile's wheel Hz
    samples = _make_profile_fault_samples(
        profile=correct_profile,
        fault_sensor=SENSOR_FL,
        sensors=[SENSOR_FL],
        speed_kmh=SPEED_MID,
    )

    # Analyze with wrong metadata — should not crash
    meta_wrong = _profile_metadata(wrong_profile)
    summary_wrong = run_analysis(samples, metadata=meta_wrong)

    # Basic structural contract: summary must have valid fields
    assert "top_causes" in summary_wrong
    assert "warnings" in summary_wrong

    # Analyze with correct metadata too — should work
    meta_correct = _profile_metadata(correct_profile)
    summary_correct = run_analysis(samples, metadata=meta_correct)
    conf_correct = top_confidence(summary_correct)
    assert conf_correct >= 0.25, (
        f"Correct profile should detect fault: profile={correct_profile['name']}"
    )


# ===================================================================
# P5 – Wheel Hz sanity: each profile produces distinct wheel Hz
# 5 profiles = 5 sanity-check cases
# ===================================================================
@pytest.mark.parametrize("profile", _PROFILES, ids=_PROFILE_IDS)
def test_wheel_hz_sanity(profile: dict[str, Any]) -> None:
    """Each profile's tire circumference produces a reasonable wheel Hz."""
    circ = _profile_circ(profile)
    assert 1.5 < circ < 3.5, f"Tire circumference {circ:.3f}m out of expected range"

    for speed in [30.0, 60.0, 100.0, 120.0]:
        whz = _profile_wheel_hz(profile, speed)
        # Wheel Hz should be between ~3 and ~25 for normal road speeds
        assert 3.0 < whz < 25.0, (
            f"wheel_hz={whz:.2f} at {speed} km/h out of expected range "
            f"for profile={profile['name']}"
        )

    # Engine Hz should be higher than wheel Hz (gear multiplication)
    ehz = _profile_engine_hz(profile, 80.0)
    whz = _profile_wheel_hz(profile, 80.0)
    assert ehz > whz, f"Engine Hz ({ehz:.2f}) should exceed wheel Hz ({whz:.2f})"
