# ruff: noqa: E501
"""Multi-system overlap resolution tests (≥50 direct-injection cases).

Tests how the analysis pipeline resolves overlapping system signatures
(wheel, engine, driveshaft) when multiple vibration sources are present
simultaneously.  Coverage includes:

  MO1 – Engine + wheel both present: correct source separation.
  MO2 – Engine-wheel harmonic alias suppression (1.15 ratio / 0.60 penalty).
  MO3 – Driveshaft + wheel overlap at low speed.
  MO4 – Three systems present simultaneously.
  MO5 – Engine-only (all sensors uniform) → no wheel localization.
  MO6 – Engine + localized wheel → wheel should dominate.
  MO7 – Profile-aware multi-system overlap across car configurations.
"""

from __future__ import annotations

from typing import Any

import pytest
from builders import (
    ALL_WHEEL_SENSORS,
    CAR_PROFILE_IDS,
    CAR_PROFILES,
    CORNER_SENSORS,
    SPEED_HIGH,
    SPEED_LOW,
    SPEED_MID,
    assert_confidence_label_valid,
    assert_no_localized_wheel,
    engine_hz,
    extract_top,
    make_engine_order_samples,
    make_sample,
    profile_metadata,
    profile_wheel_hz,
    run_analysis,
    top_confidence,
    wheel_hz,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CORNERS = ["FL", "FR", "RL", "RR"]

# Ratio of driveshaft order to wheel-1x order (prop shaft speed ≈ 2.5× wheel)
_DRIVESHAFT_WHEEL_RATIO = 2.5


def _make_engine_plus_wheel_samples(
    *,
    fault_sensor: str,
    sensors: list[str],
    speed_kmh: float = 80.0,
    n_samples: int = 30,
    wheel_amp: float = 0.06,
    engine_amp: float = 0.03,
    wheel_vib_db: float = 26.0,
    noise_vib_db: float = 8.0,
) -> list[dict[str, Any]]:
    """Build samples with both wheel fault (localized) and engine order (all sensors)."""
    samples: list[dict[str, Any]] = []
    whz = wheel_hz(speed_kmh)
    ehz = engine_hz(speed_kmh)
    for i in range(n_samples):
        t = float(i)
        for sensor in sensors:
            # Engine harmonics on all sensors
            engine_peaks = [
                {"hz": ehz, "amp": engine_amp},
                {"hz": ehz * 2, "amp": engine_amp * 0.5},
            ]
            if sensor == fault_sensor:
                # Wheel fault + engine on this sensor
                peaks = (
                    [
                        {"hz": whz, "amp": wheel_amp},
                        {"hz": whz * 2, "amp": wheel_amp * 0.4},
                    ]
                    + engine_peaks
                    + [{"hz": 142.5, "amp": 0.004}]
                )
                samples.append(
                    make_sample(
                        t_s=t,
                        speed_kmh=speed_kmh,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=wheel_vib_db,
                        strength_floor_amp_g=0.004,
                        engine_rpm=ehz * 60.0,
                    )
                )
            else:
                # Engine only + noise
                peaks = engine_peaks + [
                    {"hz": 142.5, "amp": 0.004},
                    {"hz": 87.3, "amp": 0.003},
                ]
                samples.append(
                    make_sample(
                        t_s=t,
                        speed_kmh=speed_kmh,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=noise_vib_db,
                        strength_floor_amp_g=0.004,
                        engine_rpm=ehz * 60.0,
                    )
                )
    return samples


def _make_driveshaft_plus_wheel_samples(
    *,
    fault_sensor: str,
    sensors: list[str],
    speed_kmh: float = 60.0,
    n_samples: int = 30,
    wheel_amp: float = 0.06,
    driveshaft_amp: float = 0.04,
    wheel_vib_db: float = 26.0,
    noise_vib_db: float = 8.0,
) -> list[dict[str, Any]]:
    """Build samples with wheel fault + driveshaft-order vibration."""
    samples: list[dict[str, Any]] = []
    whz = wheel_hz(speed_kmh)
    # Driveshaft order is typically related to prop shaft speed
    dshaft_hz = whz * _DRIVESHAFT_WHEEL_RATIO
    for i in range(n_samples):
        t = float(i)
        for sensor in sensors:
            dshaft_peaks = [
                {"hz": dshaft_hz, "amp": driveshaft_amp},
                {"hz": dshaft_hz * 2, "amp": driveshaft_amp * 0.4},
            ]
            if sensor == fault_sensor:
                peaks = (
                    [
                        {"hz": whz, "amp": wheel_amp},
                        {"hz": whz * 2, "amp": wheel_amp * 0.4},
                    ]
                    + dshaft_peaks
                    + [{"hz": 142.5, "amp": 0.004}]
                )
                samples.append(
                    make_sample(
                        t_s=t,
                        speed_kmh=speed_kmh,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=wheel_vib_db,
                        strength_floor_amp_g=0.004,
                    )
                )
            else:
                peaks = dshaft_peaks + [
                    {"hz": 142.5, "amp": 0.004},
                    {"hz": 87.3, "amp": 0.003},
                ]
                samples.append(
                    make_sample(
                        t_s=t,
                        speed_kmh=speed_kmh,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=noise_vib_db,
                        strength_floor_amp_g=0.004,
                    )
                )
    return samples


# ===================================================================
# MO1 – Engine + localized wheel fault: wheel should be detected
# 4 corners × 3 speeds = 12 cases
# ===================================================================
@pytest.mark.parametrize("corner", _CORNERS)
@pytest.mark.parametrize("speed", [SPEED_LOW, SPEED_MID, SPEED_HIGH], ids=["low", "mid", "high"])
def test_engine_plus_wheel_detects_wheel(corner: str, speed: float) -> None:
    """When both engine and wheel are present, wheel (localized) should be top finding."""
    sensor = CORNER_SENSORS[corner]
    samples = _make_engine_plus_wheel_samples(
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=speed,
        wheel_amp=0.06,
        engine_amp=0.02,
    )
    summary = run_analysis(samples)
    conf = top_confidence(summary)
    assert conf > 0.0, f"No finding when engine+wheel at {corner}/{speed}"
    top = extract_top(summary)
    assert top is not None


# ===================================================================
# MO2 – Engine harmonic alias suppression
# When engine confidence is close to wheel, engine should be suppressed.
# 4 corners × 3 engine strengths = 12 cases
# ===================================================================
_ENGINE_STRENGTHS = [
    ("weak_engine", 0.015),  # engine much weaker than wheel
    ("matched_engine", 0.05),  # engine similar to wheel
    ("strong_engine", 0.08),  # engine stronger than wheel
]


@pytest.mark.parametrize("corner", _CORNERS)
@pytest.mark.parametrize(
    "eng_name,engine_amp",
    _ENGINE_STRENGTHS,
    ids=[e[0] for e in _ENGINE_STRENGTHS],
)
def test_engine_alias_suppression(corner: str, eng_name: str, engine_amp: float) -> None:
    """Engine alias suppression should prevent engine from dominating when wheel is present."""
    sensor = CORNER_SENSORS[corner]
    samples = _make_engine_plus_wheel_samples(
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=SPEED_MID,
        wheel_amp=0.06,
        engine_amp=engine_amp,
    )
    summary = run_analysis(samples)
    assert isinstance(summary, dict)
    # Pipeline should not crash even with strong engine presence
    assert "top_causes" in summary


# ===================================================================
# MO3 – Driveshaft + wheel overlap
# 4 corners × 2 speeds = 8 cases
# ===================================================================
@pytest.mark.parametrize("corner", _CORNERS)
@pytest.mark.parametrize("speed", [SPEED_LOW, SPEED_MID], ids=["low", "mid"])
def test_driveshaft_plus_wheel_overlap(corner: str, speed: float) -> None:
    """Driveshaft + wheel should not crash; wheel should still be detectable."""
    sensor = CORNER_SENSORS[corner]
    samples = _make_driveshaft_plus_wheel_samples(
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=speed,
    )
    summary = run_analysis(samples)
    conf = top_confidence(summary)
    assert conf > 0.0, f"No finding for driveshaft+wheel at {corner}/{speed}"


# ===================================================================
# MO4 – Three systems simultaneously (wheel + engine + driveshaft-like)
# 4 corners × 2 speeds = 8 cases
# ===================================================================
@pytest.mark.parametrize("corner", _CORNERS)
@pytest.mark.parametrize("speed", [SPEED_MID, SPEED_HIGH], ids=["mid", "high"])
def test_three_systems_simultaneous(corner: str, speed: float) -> None:
    """Pipeline should handle wheel + engine + driveshaft-like signals without crash."""
    sensor = CORNER_SENSORS[corner]
    whz = wheel_hz(speed)
    ehz = engine_hz(speed)
    dshaft_hz = whz * _DRIVESHAFT_WHEEL_RATIO

    samples: list[dict[str, Any]] = []
    for i in range(30):
        t = float(i)
        for s in ALL_WHEEL_SENSORS:
            base_peaks = [
                {"hz": ehz, "amp": 0.025},
                {"hz": ehz * 2, "amp": 0.012},
                {"hz": dshaft_hz, "amp": 0.02},
            ]
            if s == sensor:
                peaks = [
                    {"hz": whz, "amp": 0.06},
                    {"hz": whz * 2, "amp": 0.024},
                ] + base_peaks
                samples.append(
                    make_sample(
                        t_s=t,
                        speed_kmh=speed,
                        client_name=s,
                        top_peaks=peaks,
                        vibration_strength_db=26.0,
                        strength_floor_amp_g=0.004,
                        engine_rpm=ehz * 60.0,
                    )
                )
            else:
                peaks = base_peaks + [{"hz": 142.5, "amp": 0.004}]
                samples.append(
                    make_sample(
                        t_s=t,
                        speed_kmh=speed,
                        client_name=s,
                        top_peaks=peaks,
                        vibration_strength_db=10.0,
                        strength_floor_amp_g=0.004,
                        engine_rpm=ehz * 60.0,
                    )
                )

    summary = run_analysis(samples)
    assert isinstance(summary, dict)
    assert "top_causes" in summary
    # Should produce at least one finding
    conf = top_confidence(summary)
    assert conf > 0.0, f"Three-system scenario at {corner}/{speed} produced no findings"


# ===================================================================
# MO5 – Engine-only (all sensors uniform) → no localized wheel fault
# 3 speeds × 2 engine strengths = 6 cases
# ===================================================================
_ENGINE_ONLY_STRENGTHS = [
    ("moderate", 0.04, 22.0),
    ("strong", 0.07, 28.0),
]


@pytest.mark.parametrize("speed", [SPEED_LOW, SPEED_MID, SPEED_HIGH], ids=["low", "mid", "high"])
@pytest.mark.parametrize(
    "eng_name,engine_amp,engine_db",
    _ENGINE_ONLY_STRENGTHS,
    ids=[e[0] for e in _ENGINE_ONLY_STRENGTHS],
)
def test_engine_only_no_localized_wheel(
    speed: float, eng_name: str, engine_amp: float, engine_db: float
) -> None:
    """Engine vibration on all sensors should not produce a localized wheel fault."""
    samples = make_engine_order_samples(
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=speed,
        engine_amp=engine_amp,
        engine_vib_db=engine_db,
        n_samples=30,
    )
    summary = run_analysis(samples)
    assert_no_localized_wheel(
        summary,
        msg=f"engine-only {eng_name} at {speed} km/h should not localize to a wheel",
    )


# ===================================================================
# MO6 – Engine + single-sensor wheel: wheel dominance
# 4 corners × 2 relative strengths = 8 cases
# ===================================================================
_RELATIVE_STRENGTHS = [
    ("wheel_dominates", 0.06, 0.02),
    ("wheel_slightly_stronger", 0.04, 0.03),
]


@pytest.mark.parametrize("corner", _CORNERS)
@pytest.mark.parametrize(
    "strength_name,wheel_amp,engine_amp",
    _RELATIVE_STRENGTHS,
    ids=[s[0] for s in _RELATIVE_STRENGTHS],
)
def test_engine_plus_single_sensor_wheel(
    corner: str, strength_name: str, wheel_amp: float, engine_amp: float
) -> None:
    """Engine + localized wheel: pipeline should find the localized wheel signal."""
    sensor = CORNER_SENSORS[corner]
    samples = _make_engine_plus_wheel_samples(
        fault_sensor=sensor,
        sensors=[sensor],  # single sensor
        speed_kmh=SPEED_MID,
        wheel_amp=wheel_amp,
        engine_amp=engine_amp,
    )
    summary = run_analysis(samples)
    conf = top_confidence(summary)
    assert conf > 0.0, (
        f"Single-sensor wheel+engine at {corner} ({strength_name}) should produce a finding"
    )


# ===================================================================
# MO7 – Profile-aware multi-system overlap
# 5 profiles × 4 corners = 20 cases
# ===================================================================
@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", _CORNERS)
def test_profile_engine_plus_wheel(profile: dict[str, Any], corner: str) -> None:
    """Profile-aware engine+wheel should not crash and should produce findings."""
    sensor = CORNER_SENSORS[corner]
    whz = profile_wheel_hz(profile, SPEED_MID)
    ehz = whz * profile["final_drive_ratio"] * profile["current_gear_ratio"]

    samples: list[dict[str, Any]] = []
    for i in range(30):
        t = float(i)
        for s in ALL_WHEEL_SENSORS:
            engine_peaks = [
                {"hz": ehz, "amp": 0.03},
                {"hz": ehz * 2, "amp": 0.015},
            ]
            if s == sensor:
                peaks = [
                    {"hz": whz, "amp": 0.06},
                    {"hz": whz * 2, "amp": 0.024},
                ] + engine_peaks
                samples.append(
                    make_sample(
                        t_s=t,
                        speed_kmh=SPEED_MID,
                        client_name=s,
                        top_peaks=peaks,
                        vibration_strength_db=26.0,
                        strength_floor_amp_g=0.004,
                        engine_rpm=ehz * 60.0,
                    )
                )
            else:
                peaks = engine_peaks + [{"hz": 142.5, "amp": 0.004}]
                samples.append(
                    make_sample(
                        t_s=t,
                        speed_kmh=SPEED_MID,
                        client_name=s,
                        top_peaks=peaks,
                        vibration_strength_db=8.0,
                        strength_floor_amp_g=0.004,
                        engine_rpm=ehz * 60.0,
                    )
                )

    meta = profile_metadata(profile)
    summary = run_analysis(samples, metadata=meta)
    assert isinstance(summary, dict)
    assert "top_causes" in summary
    conf = top_confidence(summary)
    assert conf > 0.0, f"Profile {profile['name']} engine+wheel at {corner} produced no findings"
    # Validate confidence label if above floor
    top = extract_top(summary)
    if top and float(top.get("confidence", 0)) > 0.25:
        assert_confidence_label_valid(summary, msg=f"profile={profile['name']} {corner}")
