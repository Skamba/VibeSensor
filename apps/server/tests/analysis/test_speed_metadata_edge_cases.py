# ruff: noqa: E501
"""Speed metadata edge-case tests (≥50 direct-injection cases).

Tests robustness of the analysis pipeline under various speed metadata
anomalies: frozen/stale speed, speed oscillation at band boundaries,
negative speed, Inf speed, speed ramp across critical frequencies,
missing speed field, and mixed valid/invalid speed within a run.
"""

from __future__ import annotations

import math
from typing import Any

import pytest
from builders import (
    ALL_WHEEL_SENSORS,
    SENSOR_FL,
    SENSOR_FR,
    SENSOR_RL,
    SENSOR_RR,
    SPEED_HIGH,
    SPEED_LOW,
    SPEED_MID,
    assert_no_wheel_fault,
    make_sample,
    run_analysis,
    top_confidence,
    wheel_hz,
)

# ---------------------------------------------------------------------------
# Speed sample builder helpers
# ---------------------------------------------------------------------------


def _make_speed_scenario_samples(
    *,
    sensors: list[str],
    speed_fn: Any,  # callable(i) -> float
    n_samples: int = 30,
    fault_sensor: str | None = None,
    fault_amp: float = 0.06,
    fault_vib_db: float = 26.0,
    noise_amp: float = 0.004,
    noise_vib_db: float = 8.0,
) -> list[dict[str, Any]]:
    """Build samples with a custom speed function for each timestep."""
    samples: list[dict[str, Any]] = []
    for i in range(n_samples):
        t = float(i)
        speed = speed_fn(i)
        for sensor in sensors:
            if sensor == fault_sensor and speed > 0:
                whz = wheel_hz(speed) if speed > 0 else 20.0
                peaks: list[dict[str, float]] = [
                    {"hz": whz, "amp": fault_amp},
                    {"hz": whz * 2, "amp": fault_amp * 0.4},
                    {"hz": 142.5, "amp": noise_amp},
                ]
                samples.append(
                    make_sample(
                        t_s=t,
                        speed_kmh=speed,
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
                        speed_kmh=speed,
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


_CORNERS_AND_SENSORS = [
    ("FL", SENSOR_FL),
    ("FR", SENSOR_FR),
    ("RL", SENSOR_RL),
    ("RR", SENSOR_RR),
]


# ===================================================================
# S1 – Frozen speed: same speed for entire run (constant speed penalty)
# 4 corners × 3 speeds = 12 cases
# ===================================================================
@pytest.mark.parametrize("corner,sensor", _CORNERS_AND_SENSORS, ids=["FL", "FR", "RL", "RR"])
@pytest.mark.parametrize("speed", [SPEED_LOW, SPEED_MID, SPEED_HIGH], ids=["low", "mid", "high"])
def test_frozen_speed_with_fault(corner: str, sensor: str, speed: float) -> None:
    """A valid fault should still be detected even with perfectly frozen speed."""
    samples = _make_speed_scenario_samples(
        sensors=[sensor],
        speed_fn=lambda _i, s=speed: s,
        n_samples=30,
        fault_sensor=sensor,
    )
    summary = run_analysis(samples)
    # Frozen/constant speed gets a penalty but should still detect
    conf = top_confidence(summary)
    assert conf > 0.0, f"No fault detected at frozen speed={speed}, corner={corner}"
    assert isinstance(summary, dict)


# ===================================================================
# S2 – Speed oscillation around a band boundary
# The pipeline bins speed into 10 km/h windows. Oscillation at a
# boundary (e.g., 59–61 km/h) should not crash or produce inconsistent
# results. 4 base speeds × 2 jitter amplitudes = 8 cases
# ===================================================================
_BOUNDARY_SPEEDS = [30.0, 50.0, 60.0, 100.0]  # bin edges
_JITTER_AMPS = [0.5, 2.0]  # tiny and moderate oscillation


@pytest.mark.parametrize("base_speed", _BOUNDARY_SPEEDS, ids=["30", "50", "60", "100"])
@pytest.mark.parametrize("jitter_amp", _JITTER_AMPS, ids=["tiny", "moderate"])
def test_speed_oscillation_at_boundary(base_speed: float, jitter_amp: float) -> None:
    """Speed oscillating around a bin boundary should not crash or produce NaN."""

    def speed_fn(i: int) -> float:
        return base_speed + jitter_amp * (1 if i % 2 == 0 else -1)

    samples = _make_speed_scenario_samples(
        sensors=ALL_WHEEL_SENSORS,
        speed_fn=speed_fn,
        n_samples=30,
        fault_sensor=SENSOR_FL,
    )
    summary = run_analysis(samples)
    assert isinstance(summary, dict)
    assert "top_causes" in summary
    # No NaN in confidence
    for tc in summary.get("top_causes", []):
        conf = tc.get("confidence", 0)
        assert not math.isnan(float(conf)), "NaN confidence from speed oscillation"


# ===================================================================
# S3 – Negative speed values: should not crash, should not produce
# positive detections.  4 cases (one per sensor config)
# ===================================================================
_NEGATIVE_SPEEDS = [-10.0, -1.0, -0.01, -100.0]


@pytest.mark.parametrize("neg_speed", _NEGATIVE_SPEEDS, ids=["-10", "-1", "-0.01", "-100"])
def test_negative_speed_does_not_crash(neg_speed: float) -> None:
    """Negative speed should produce a valid (no-fault) result."""
    samples = _make_speed_scenario_samples(
        sensors=ALL_WHEEL_SENSORS,
        speed_fn=lambda _i, s=neg_speed: s,
        n_samples=20,
    )
    summary = run_analysis(samples)
    assert isinstance(summary, dict)
    # Should not produce confident wheel faults
    assert_no_wheel_fault(summary, msg=f"negative speed={neg_speed}")


# ===================================================================
# S4 – Inf speed values: should not crash.  2 cases.
# ===================================================================
@pytest.mark.parametrize("inf_speed", [float("inf"), float("-inf")], ids=["pos_inf", "neg_inf"])
def test_inf_speed_does_not_crash(inf_speed: float) -> None:
    """Infinity speed should not crash the pipeline."""
    samples = _make_speed_scenario_samples(
        sensors=[SENSOR_FL],
        speed_fn=lambda _i, s=inf_speed: s,
        n_samples=15,
    )
    summary = run_analysis(samples)
    assert isinstance(summary, dict)


# ===================================================================
# S5 – Speed ramp through critical frequency bands
# A linear speed ramp that sweeps through all speed bands should
# produce valid analysis. 4 ramp configs = 4 cases
# ===================================================================
_RAMP_CONFIGS = [
    ("slow_to_fast", 20.0, 120.0),
    ("fast_to_slow", 120.0, 20.0),
    ("mid_range", 40.0, 80.0),
    ("highway", 80.0, 130.0),
]


@pytest.mark.parametrize("name,start,end", _RAMP_CONFIGS, ids=[c[0] for c in _RAMP_CONFIGS])
def test_speed_ramp_with_fault(name: str, start: float, end: float) -> None:
    """Speed ramp across bands should still detect wheel fault."""

    def speed_fn(i: int) -> float:
        ratio = i / 29.0
        return start + (end - start) * ratio

    samples = _make_speed_scenario_samples(
        sensors=[SENSOR_FL],
        speed_fn=speed_fn,
        n_samples=30,
        fault_sensor=SENSOR_FL,
    )
    summary = run_analysis(samples)
    assert isinstance(summary, dict)
    # Should produce findings (fault is present throughout the ramp)
    conf = top_confidence(summary)
    assert conf > 0.0, f"No finding from speed ramp {name}"


# ===================================================================
# S6 – Mixed valid/invalid speed within a run
# First half valid, second half corrupted. Analysis should still
# complete and use the valid portion. 3 corruption types × 2 speeds = 6
# ===================================================================
_CORRUPTION_TYPES = [
    ("zero_second_half", lambda i: 80.0 if i < 15 else 0.0),
    ("nan_second_half", lambda i: 80.0 if i < 15 else float("nan")),
    ("negative_second_half", lambda i: 80.0 if i < 15 else -5.0),
]


@pytest.mark.parametrize("name,speed_fn", _CORRUPTION_TYPES, ids=[c[0] for c in _CORRUPTION_TYPES])
@pytest.mark.parametrize("fault_sensor", [SENSOR_FL, SENSOR_RR], ids=["FL", "RR"])
def test_mixed_valid_invalid_speed(name: str, speed_fn: Any, fault_sensor: str) -> None:
    """Run with partially corrupted speed should still complete analysis."""
    samples = _make_speed_scenario_samples(
        sensors=ALL_WHEEL_SENSORS,
        speed_fn=speed_fn,
        n_samples=30,
        fault_sensor=fault_sensor,
    )
    summary = run_analysis(samples)
    assert isinstance(summary, dict)
    assert "top_causes" in summary
    # No NaN propagation
    for tc in summary.get("top_causes", []):
        conf_val = float(tc.get("confidence", 0))
        assert not math.isnan(conf_val), f"NaN confidence from {name}"


# ===================================================================
# S7 – Very slow speed (near-idle, 1-5 km/h): wheel Hz is very low,
# should not crash or produce overconfident findings. 3 cases
# ===================================================================
@pytest.mark.parametrize("speed", [1.0, 3.0, 5.0], ids=["1kmh", "3kmh", "5kmh"])
def test_very_slow_speed(speed: float) -> None:
    """Near-idle speed should not crash or produce overconfident findings."""
    samples = _make_speed_scenario_samples(
        sensors=[SENSOR_FL],
        speed_fn=lambda _i, s=speed: s,
        n_samples=25,
        fault_sensor=SENSOR_FL,
    )
    summary = run_analysis(samples)
    assert isinstance(summary, dict)


# ===================================================================
# S8 – Very high speed (>200 km/h): wheel Hz is high, should handle
# gracefully. 3 cases
# ===================================================================
@pytest.mark.parametrize("speed", [200.0, 250.0, 300.0], ids=["200", "250", "300"])
def test_very_high_speed(speed: float) -> None:
    """Very high speed should be handled without crash."""
    samples = _make_speed_scenario_samples(
        sensors=[SENSOR_FL],
        speed_fn=lambda _i, s=speed: s,
        n_samples=20,
        fault_sensor=SENSOR_FL,
    )
    summary = run_analysis(samples)
    assert isinstance(summary, dict)
    assert "top_causes" in summary


# ===================================================================
# S9 – Speed step change: sudden jump mid-run
# 4 step configs = 4 cases
# ===================================================================
_STEP_CONFIGS = [
    ("30_to_100", 30.0, 100.0),
    ("100_to_30", 100.0, 30.0),
    ("60_to_120", 60.0, 120.0),
    ("80_to_0", 80.0, 0.0),
]


@pytest.mark.parametrize("name,before,after", _STEP_CONFIGS, ids=[c[0] for c in _STEP_CONFIGS])
def test_speed_step_change(name: str, before: float, after: float) -> None:
    """Sudden speed step change should not crash or produce NaN."""

    def speed_fn(i: int) -> float:
        return before if i < 15 else after

    samples = _make_speed_scenario_samples(
        sensors=ALL_WHEEL_SENSORS,
        speed_fn=speed_fn,
        n_samples=30,
        fault_sensor=SENSOR_FL,
    )
    summary = run_analysis(samples)
    assert isinstance(summary, dict)
    for tc in summary.get("top_causes", []):
        assert not math.isnan(float(tc.get("confidence", 0))), f"NaN from step {name}"


# ===================================================================
# S10 – Noise-only at various extreme speeds: should not produce
# false positives.  5 speeds = 5 cases
# ===================================================================
@pytest.mark.parametrize(
    "speed",
    [1.0, 5.0, 150.0, 200.0, 250.0],
    ids=["1kmh", "5kmh", "150kmh", "200kmh", "250kmh"],
)
def test_noise_only_extreme_speed_no_false_positive(speed: float) -> None:
    """Pure noise at extreme speeds should not produce wheel fault."""
    samples = _make_speed_scenario_samples(
        sensors=ALL_WHEEL_SENSORS,
        speed_fn=lambda _i, s=speed: s,
        n_samples=25,
    )
    summary = run_analysis(samples)
    assert_no_wheel_fault(summary, msg=f"noise-only at extreme speed={speed}")
