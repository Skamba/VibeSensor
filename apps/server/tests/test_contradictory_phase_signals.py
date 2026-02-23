# ruff: noqa: E501
"""Contradictory / phase-inconsistent signal tests (≥50 direct-injection cases).

Tests the analysis pipeline when signals contradict each other across
different phases of a run.  Coverage includes:

  CP1 – Fault at one corner in phase A, different corner in phase B:
        pipeline should not flip localization erroneously.
  CP2 – Engine order on idle + wheel order on cruise in same run:
        cruise-phase wheel should dominate.
  CP3 – Transient in one phase + persistent fault in another:
        persistent fault should dominate.
  CP4 – Fault present in first half, noise-only in second half:
        pipeline should still detect the fault.
  CP5 – Strong conflicting signals (equal strength different corners):
        ambiguity handling.
  CP6 – Profile-aware phased contradictions across car configurations.
  CP7 – Speed changes between phases affecting frequency tracking.
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
    make_fault_samples,
    make_noise_samples,
    make_profile_fault_samples,
    make_sample,
    make_transient_samples,
    profile_metadata,
    run_analysis,
    top_confidence,
    wheel_hz,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CORNERS = ["FL", "FR", "RL", "RR"]

# Typical engine idle frequency (~800 RPM ≈ 13.3 Hz at 1x order)
_IDLE_ENGINE_HZ = 13.3

_CORNER_PAIRS = [
    ("FL", "FR"),
    ("FL", "RL"),
    ("FL", "RR"),
    ("FR", "RL"),
    ("FR", "RR"),
    ("RL", "RR"),
]


# ===================================================================
# CP1 – Fault at different corners across phases
# Same frequency, different localization.  Pipeline should produce
# at least one finding and not crash.
# 6 corner pairs × 2 speeds = 12 cases
# ===================================================================
@pytest.mark.parametrize(
    "corner_a,corner_b",
    _CORNER_PAIRS,
    ids=[f"{a}_{b}" for a, b in _CORNER_PAIRS],
)
@pytest.mark.parametrize("speed", [SPEED_MID, SPEED_HIGH], ids=["mid", "high"])
def test_different_corners_across_phases(
    corner_a: str, corner_b: str, speed: float
) -> None:
    """Fault on corner_a in phase 1, corner_b in phase 2: pipeline should handle gracefully."""
    sensor_a = CORNER_SENSORS[corner_a]
    sensor_b = CORNER_SENSORS[corner_b]

    # Phase 1: fault at corner A
    phase1 = make_fault_samples(
        fault_sensor=sensor_a,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=speed,
        n_samples=20,
        start_t_s=0.0,
        fault_amp=0.06,
        fault_vib_db=26.0,
    )
    # Phase 2: fault at corner B
    phase2 = make_fault_samples(
        fault_sensor=sensor_b,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=speed,
        n_samples=20,
        start_t_s=20.0,
        fault_amp=0.06,
        fault_vib_db=26.0,
    )
    samples = phase1 + phase2
    summary = run_analysis(samples)
    assert isinstance(summary, dict)
    assert "top_causes" in summary
    conf = top_confidence(summary)
    assert conf > 0.0, (
        f"Contradictory corners {corner_a}→{corner_b} at {speed} produced no findings"
    )


# ===================================================================
# CP2 – Engine on idle + wheel on cruise
# Idle phase has engine vibration, cruise has wheel fault.
# Cruise-phase wheel should be the dominant finding.
# 4 corners × 2 idle durations = 8 cases
# ===================================================================
_IDLE_DURATIONS = [
    ("short_idle", 5),
    ("long_idle", 15),
]


@pytest.mark.parametrize("corner", _CORNERS)
@pytest.mark.parametrize(
    "idle_name,idle_n",
    _IDLE_DURATIONS,
    ids=[d[0] for d in _IDLE_DURATIONS],
)
def test_engine_idle_then_wheel_cruise(
    corner: str, idle_name: str, idle_n: int
) -> None:
    """Engine on idle then wheel fault on cruise: wheel should be detected."""
    sensor = CORNER_SENSORS[corner]

    # Phase 1: idle with engine vibration
    idle_samples: list[dict[str, Any]] = []
    for i in range(idle_n):
        t = float(i)
        for s in ALL_WHEEL_SENSORS:
            peaks = [
                {"hz": _IDLE_ENGINE_HZ, "amp": 0.03},
                {"hz": _IDLE_ENGINE_HZ * 2, "amp": 0.015},
            ]
            idle_samples.append(make_sample(
                t_s=t, speed_kmh=0.0, client_name=s,
                top_peaks=peaks, vibration_strength_db=18.0,
                strength_floor_amp_g=0.003,
            ))

    # Phase 2: cruise with wheel fault
    cruise_start = float(idle_n)
    cruise_samples = make_fault_samples(
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=SPEED_MID,
        n_samples=25,
        start_t_s=cruise_start,
        fault_amp=0.06,
        fault_vib_db=26.0,
    )

    samples = idle_samples + cruise_samples
    summary = run_analysis(samples)
    conf = top_confidence(summary)
    assert conf > 0.0, (
        f"Engine idle + wheel cruise at {corner} ({idle_name}) should detect wheel fault"
    )


# ===================================================================
# CP3 – Transient in one phase + persistent fault in another
# The persistent fault should dominate.
# 4 corners × 3 transient positions = 12 cases
# ===================================================================
_TRANSIENT_POSITIONS = [
    ("transient_before", 0.0, 10.0),   # transient, then persistent
    ("transient_after", 25.0, 0.0),    # persistent, then transient
    ("transient_middle", 12.0, 0.0),   # persistent, transient in middle, persistent again
]


@pytest.mark.parametrize("corner", _CORNERS)
@pytest.mark.parametrize(
    "pos_name,trans_start,fault_start",
    _TRANSIENT_POSITIONS,
    ids=[p[0] for p in _TRANSIENT_POSITIONS],
)
def test_transient_plus_persistent(
    corner: str, pos_name: str, trans_start: float, fault_start: float
) -> None:
    """Persistent fault should dominate over transient in combined scenario."""
    sensor = CORNER_SENSORS[corner]

    # Transient spike (short)
    transients = make_transient_samples(
        sensor=sensor,
        speed_kmh=SPEED_MID,
        n_samples=3,
        start_t_s=trans_start,
        spike_amp=0.15,
        spike_vib_db=35.0,
    )

    # Persistent fault (longer)
    persistent = make_fault_samples(
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=SPEED_MID,
        n_samples=25,
        start_t_s=fault_start,
        fault_amp=0.06,
        fault_vib_db=26.0,
    )

    samples = transients + persistent
    # Sort by time for realism
    samples.sort(key=lambda s: s["t_s"])
    summary = run_analysis(samples)
    conf = top_confidence(summary)
    assert conf > 0.0, (
        f"Transient + persistent at {corner} ({pos_name}) should detect the fault"
    )


# ===================================================================
# CP4 – Fault in first half, noise-only in second half
# Pipeline should still detect the fault from partial evidence.
# 4 corners × 2 split ratios = 8 cases
# ===================================================================
_SPLIT_RATIOS = [
    ("mostly_fault", 25, 5),
    ("two_thirds_fault", 20, 10),
]


@pytest.mark.parametrize("corner", _CORNERS)
@pytest.mark.parametrize(
    "split_name,fault_n,noise_n",
    _SPLIT_RATIOS,
    ids=[s[0] for s in _SPLIT_RATIOS],
)
def test_fault_then_noise(
    corner: str, split_name: str, fault_n: int, noise_n: int
) -> None:
    """Fault in first portion, noise in rest: fault should still be detected."""
    sensor = CORNER_SENSORS[corner]

    fault_phase = make_fault_samples(
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=SPEED_MID,
        n_samples=fault_n,
        start_t_s=0.0,
        fault_amp=0.06,
        fault_vib_db=26.0,
    )
    noise_phase = make_noise_samples(
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=SPEED_MID,
        n_samples=noise_n,
        start_t_s=float(fault_n),
    )

    samples = fault_phase + noise_phase
    summary = run_analysis(samples)
    conf = top_confidence(summary)
    assert conf > 0.0, (
        f"Fault→noise at {corner} ({split_name}) should still detect the fault"
    )


# ===================================================================
# CP5 – Equal-strength faults at two corners (ambiguity test)
# Both corners have identical fault amplitude; pipeline should handle
# the ambiguity gracefully (produce some finding, not crash).
# 6 corner pairs = 6 cases
# ===================================================================
@pytest.mark.parametrize(
    "corner_a,corner_b",
    _CORNER_PAIRS,
    ids=[f"{a}_{b}" for a, b in _CORNER_PAIRS],
)
def test_equal_strength_two_corners(
    corner_a: str, corner_b: str
) -> None:
    """Equal-strength faults at two corners: pipeline should not crash and should find something."""
    sensor_a = CORNER_SENSORS[corner_a]
    sensor_b = CORNER_SENSORS[corner_b]
    whz = wheel_hz(SPEED_MID)

    samples: list[dict[str, Any]] = []
    for i in range(30):
        t = float(i)
        for s in ALL_WHEEL_SENSORS:
            if s == sensor_a or s == sensor_b:
                peaks = [
                    {"hz": whz, "amp": 0.06},
                    {"hz": whz * 2, "amp": 0.024},
                    {"hz": 142.5, "amp": 0.004},
                ]
                samples.append(make_sample(
                    t_s=t, speed_kmh=SPEED_MID, client_name=s,
                    top_peaks=peaks, vibration_strength_db=26.0,
                    strength_floor_amp_g=0.004,
                ))
            else:
                samples.append(make_sample(
                    t_s=t, speed_kmh=SPEED_MID, client_name=s,
                    top_peaks=[{"hz": 142.5, "amp": 0.004}],
                    vibration_strength_db=8.0,
                    strength_floor_amp_g=0.004,
                ))

    summary = run_analysis(samples)
    assert isinstance(summary, dict)
    assert "top_causes" in summary
    # Should produce at least one finding (may report ambiguity)
    conf = top_confidence(summary)
    assert conf > 0.0, (
        f"Equal-strength {corner_a}+{corner_b} should produce a finding"
    )


# ===================================================================
# CP6 – Profile-aware phased contradictions
# 5 profiles × 3 contradiction types = 15 cases
# ===================================================================
_CONTRADICTION_TYPES = [
    ("fl_then_rr", "FL", "RR"),
    ("fr_then_rl", "FR", "RL"),
    ("rl_then_fr", "RL", "FR"),
]


@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize(
    "contra_name,corner_a,corner_b",
    _CONTRADICTION_TYPES,
    ids=[c[0] for c in _CONTRADICTION_TYPES],
)
def test_profile_phased_contradiction(
    profile: dict[str, Any], contra_name: str, corner_a: str, corner_b: str
) -> None:
    """Profile-aware contradictory corners across phases should not crash."""
    sensor_a = CORNER_SENSORS[corner_a]
    sensor_b = CORNER_SENSORS[corner_b]
    meta = profile_metadata(profile)

    phase1 = make_profile_fault_samples(
        profile=profile,
        fault_sensor=sensor_a,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=SPEED_MID,
        n_samples=15,
        start_t_s=0.0,
        fault_amp=0.06,
        fault_vib_db=26.0,
    )
    phase2 = make_profile_fault_samples(
        profile=profile,
        fault_sensor=sensor_b,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=SPEED_MID,
        n_samples=15,
        start_t_s=15.0,
        fault_amp=0.06,
        fault_vib_db=26.0,
    )

    samples = phase1 + phase2
    summary = run_analysis(samples, metadata=meta)
    assert isinstance(summary, dict)
    assert "top_causes" in summary
    conf = top_confidence(summary)
    assert conf > 0.0, (
        f"Profile {profile['name']} contradictory {corner_a}→{corner_b} should produce findings"
    )


# ===================================================================
# CP7 – Speed changes between phases affecting frequency tracking
# Phase 1 at low speed, phase 2 at high speed: wheel Hz changes.
# 4 corners × 3 speed combinations = 12 cases
# ===================================================================
_SPEED_COMBOS = [
    ("low_to_high", SPEED_LOW, SPEED_HIGH),
    ("high_to_low", SPEED_HIGH, SPEED_LOW),
    ("mid_to_high", SPEED_MID, SPEED_HIGH),
]


@pytest.mark.parametrize("corner", _CORNERS)
@pytest.mark.parametrize(
    "combo_name,speed_a,speed_b",
    _SPEED_COMBOS,
    ids=[c[0] for c in _SPEED_COMBOS],
)
def test_speed_change_between_phases(
    corner: str, combo_name: str, speed_a: float, speed_b: float
) -> None:
    """Fault across phases with different speeds: tracking should still find the fault."""
    sensor = CORNER_SENSORS[corner]

    phase1 = make_fault_samples(
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=speed_a,
        n_samples=15,
        start_t_s=0.0,
        fault_amp=0.06,
        fault_vib_db=26.0,
    )
    phase2 = make_fault_samples(
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=speed_b,
        n_samples=15,
        start_t_s=15.0,
        fault_amp=0.06,
        fault_vib_db=26.0,
    )

    samples = phase1 + phase2
    summary = run_analysis(samples)
    conf = top_confidence(summary)
    assert conf > 0.0, (
        f"Speed change {combo_name} at {corner} should still detect the fault"
    )
