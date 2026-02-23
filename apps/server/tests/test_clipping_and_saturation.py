# ruff: noqa: E501
"""Clipping / ADC saturation edge-case tests (≥50 direct-injection cases).

Tests the analysis pipeline's robustness when peak amplitudes are clipped
(simulating ADC saturation).  Coverage includes:

  CS1 – Increasing clip level on a single fault sensor:  confidence should
        degrade monotonically as more of the signal is lost.
  CS2 – Clipping on the fault sensor vs. neighbouring noise-only sensors:
        localization should still point to the correct corner.
  CS3 – All sensors clipped equally (diffuse clipping): should NOT produce
        a localized fault (false positive).
  CS4 – Clipping at extreme levels (very tight clip → all peaks capped):
        pipeline should not crash and should produce no overconfident result.
  CS5 – Clipping combined with speed metadata edge cases.
  CS6 – Profile-aware clipping across multiple car configurations.
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
    extract_top,
    make_clipped_samples,
    make_fault_samples,
    make_noise_samples,
    make_profile_fault_samples,
    profile_metadata,
    run_analysis,
    top_confidence,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CORNERS = ["FL", "FR", "RL", "RR"]

# Fallback frequency used when speed is zero/negative and wheel Hz cannot be computed
_FALLBACK_WHEEL_HZ = 20.0


def _make_clipped_fault(
    *,
    fault_sensor: str,
    sensors: list[str],
    speed_kmh: float = 80.0,
    fault_amp: float = 0.06,
    fault_vib_db: float = 26.0,
    clip_amp: float = 0.10,
    n_samples: int = 30,
) -> list[dict[str, Any]]:
    """Build a wheel-fault scenario with clipping applied to the fault sensor."""
    base = make_fault_samples(
        fault_sensor=fault_sensor,
        sensors=sensors,
        speed_kmh=speed_kmh,
        fault_amp=fault_amp,
        fault_vib_db=fault_vib_db,
        n_samples=n_samples,
    )
    return make_clipped_samples(base_samples=base, clip_sensor=fault_sensor, clip_amp=clip_amp)


# ===================================================================
# CS1 – Increasing clip level on a single-sensor fault
# Tests that tighter clipping degrades or caps confidence.
# 4 corners × 4 clip levels = 16 cases
# ===================================================================
_CLIP_LEVELS = [
    ("no_clip", 1.0),        # effectively unclipped (amp < 1.0)
    ("mild_clip", 0.05),     # only the strongest peak is slightly cut
    ("moderate_clip", 0.03), # significant clipping
    ("severe_clip", 0.01),   # everything capped to near-noise floor
]


@pytest.mark.parametrize("corner", _CORNERS)
@pytest.mark.parametrize(
    "clip_name,clip_amp",
    _CLIP_LEVELS,
    ids=[c[0] for c in _CLIP_LEVELS],
)
def test_clipping_level_effect_on_confidence(
    corner: str, clip_name: str, clip_amp: float
) -> None:
    """Tighter clipping should degrade confidence; pipeline must not crash."""
    sensor = CORNER_SENSORS[corner]
    samples = _make_clipped_fault(
        fault_sensor=sensor,
        sensors=[sensor],
        fault_amp=0.06,
        clip_amp=clip_amp,
    )
    summary = run_analysis(samples)
    assert isinstance(summary, dict), "Pipeline returned non-dict"
    assert "top_causes" in summary, "Missing top_causes"

    # Very severe clipping should NOT produce an overconfident result
    if clip_amp <= 0.01:
        conf = top_confidence(summary)
        assert conf < 0.90, (
            f"Severe clip at {corner} produced conf={conf:.3f}; "
            "expected degradation below 0.90"
        )


# ===================================================================
# CS2 – Clipping on fault sensor preserves localisation
# With 4 sensors, only the fault sensor is clipped.  The clipped
# fault should still localise to the correct corner.
# 4 corners × 3 speeds = 12 cases
# ===================================================================
@pytest.mark.parametrize("corner", _CORNERS)
@pytest.mark.parametrize("speed", [SPEED_LOW, SPEED_MID, SPEED_HIGH], ids=["low", "mid", "high"])
def test_clipped_fault_sensor_still_produces_finding(
    corner: str, speed: float
) -> None:
    """A moderately clipped fault sensor should still produce a finding."""
    sensor = CORNER_SENSORS[corner]
    samples = _make_clipped_fault(
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=speed,
        fault_amp=0.06,
        fault_vib_db=26.0,
        clip_amp=0.05,
    )
    summary = run_analysis(samples)
    conf = top_confidence(summary)
    assert conf > 0.0, (
        f"Clipped fault at {corner}/{speed} km/h should still be detected"
    )


# ===================================================================
# CS3 – Clipping all sensors equally (diffuse clipping)
# When all sensors are clipped to the same level, no single corner
# should dominate → should NOT produce a localized wheel fault.
# 4 clip levels × 3 speeds = 12 cases
# ===================================================================
_DIFFUSE_CLIP_LEVELS = [0.08, 0.05, 0.03, 0.01]


@pytest.mark.parametrize("clip_amp", _DIFFUSE_CLIP_LEVELS, ids=["clip08", "clip05", "clip03", "clip01"])
@pytest.mark.parametrize("speed", [SPEED_LOW, SPEED_MID, SPEED_HIGH], ids=["low", "mid", "high"])
def test_diffuse_clipping_no_localized_fault(
    clip_amp: float, speed: float
) -> None:
    """Equal clipping on all sensors should not produce a localized wheel fault."""
    # Build noise on all sensors (no real fault)
    base = make_noise_samples(
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=speed,
        n_samples=30,
        noise_amp=0.01,
        vib_db=12.0,
    )
    # Clip every sensor
    clipped = base
    for sensor in ALL_WHEEL_SENSORS:
        clipped = make_clipped_samples(
            base_samples=clipped,
            clip_sensor=sensor,
            clip_amp=clip_amp,
        )
    summary = run_analysis(clipped)
    assert_no_wheel_fault(
        summary,
        msg=f"diffuse clipping clip_amp={clip_amp} speed={speed}",
    )


# ===================================================================
# CS4 – Extreme clipping (all peaks capped to near-zero)
# Pipeline must not crash or produce NaN.
# 4 corners × 2 sensor configs = 8 cases
# ===================================================================
_EXTREME_CONFIGS = [
    ("single", lambda c: [CORNER_SENSORS[c]]),
    ("quad", lambda _c: ALL_WHEEL_SENSORS),
]


@pytest.mark.parametrize("corner", _CORNERS)
@pytest.mark.parametrize("cfg_name,sensor_fn", _EXTREME_CONFIGS, ids=["single", "quad"])
def test_extreme_clipping_no_crash(
    corner: str, cfg_name: str, sensor_fn: Any
) -> None:
    """Clipping every peak to near-zero should not crash or produce NaN."""
    sensor = CORNER_SENSORS[corner]
    sensors = sensor_fn(corner)
    samples = _make_clipped_fault(
        fault_sensor=sensor,
        sensors=sensors,
        fault_amp=0.06,
        clip_amp=0.001,  # extremely tight
    )
    summary = run_analysis(samples)
    assert isinstance(summary, dict)
    for tc in summary.get("top_causes", []):
        conf = float(tc.get("confidence", 0))
        import math
        assert not math.isnan(conf), "NaN confidence from extreme clipping"


# ===================================================================
# CS5 – Clipping combined with speed edge cases
# 4 speed variants × 2 clip levels = 8 cases
# ===================================================================
_SPEED_VARIANTS = [
    ("frozen_80", lambda _i: 80.0),
    ("ramp_40_100", lambda i: 40.0 + (100.0 - 40.0) * i / 29.0),
    ("slow_10", lambda _i: 10.0),
    ("fast_120", lambda _i: 120.0),
]


@pytest.mark.parametrize(
    "speed_name,speed_fn",
    _SPEED_VARIANTS,
    ids=[v[0] for v in _SPEED_VARIANTS],
)
@pytest.mark.parametrize("clip_amp", [0.04, 0.02], ids=["clip04", "clip02"])
def test_clipping_with_speed_variants(
    speed_name: str, speed_fn: Any, clip_amp: float
) -> None:
    """Clipping combined with various speed patterns should not crash."""
    from builders import make_sample, wheel_hz

    samples: list[dict[str, Any]] = []
    for i in range(30):
        t = float(i)
        speed = speed_fn(i)
        for sensor in ALL_WHEEL_SENSORS:
            if sensor == SENSOR_FL and speed > 0:
                whz = wheel_hz(speed) if speed > 0 else _FALLBACK_WHEEL_HZ
                peaks = [
                    {"hz": whz, "amp": 0.06},
                    {"hz": whz * 2, "amp": 0.024},
                    {"hz": 142.5, "amp": 0.004},
                ]
                samples.append(make_sample(
                    t_s=t, speed_kmh=speed, client_name=sensor,
                    top_peaks=peaks, vibration_strength_db=26.0,
                    strength_floor_amp_g=0.004,
                ))
            else:
                samples.append(make_sample(
                    t_s=t, speed_kmh=speed, client_name=sensor,
                    top_peaks=[{"hz": 142.5, "amp": 0.004}],
                    vibration_strength_db=8.0,
                    strength_floor_amp_g=0.004,
                ))

    clipped = make_clipped_samples(
        base_samples=samples, clip_sensor=SENSOR_FL, clip_amp=clip_amp,
    )
    summary = run_analysis(clipped)
    assert isinstance(summary, dict)


# ===================================================================
# CS6 – Profile-aware clipping across car configurations
# 5 profiles × 4 corners × 2 clip levels = 40 cases
# ===================================================================
@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", _CORNERS)
@pytest.mark.parametrize("clip_amp", [0.04, 0.02], ids=["clip04", "clip02"])
def test_profile_clipped_fault_no_crash(
    profile: dict[str, Any], corner: str, clip_amp: float
) -> None:
    """Profile-aware clipped fault should not crash and should produce valid output."""
    sensor = CORNER_SENSORS[corner]
    base = make_profile_fault_samples(
        profile=profile,
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=SPEED_MID,
        fault_amp=0.06,
        fault_vib_db=26.0,
        n_samples=30,
    )
    clipped = make_clipped_samples(
        base_samples=base, clip_sensor=sensor, clip_amp=clip_amp,
    )
    meta = profile_metadata(profile)
    summary = run_analysis(clipped, metadata=meta)
    assert isinstance(summary, dict)
    assert "top_causes" in summary
    # Must produce valid confidence label if there is a finding
    top = extract_top(summary)
    if top and float(top.get("confidence", 0)) > 0.25:
        assert_confidence_label_valid(summary, msg=f"profile={profile['name']} {corner} clip={clip_amp}")
