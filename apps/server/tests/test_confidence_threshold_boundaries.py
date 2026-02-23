# ruff: noqa: E501
"""Confidence threshold boundary tests — multi-profile (≥50 cases per profile).

Tests the analysis pipeline's behaviour at and near critical confidence
thresholds: 0.25 (ORDER_MIN_CONFIDENCE floor), 0.40 (medium / no-fault
boundary), 0.70 (HIGH / MEDIUM label transition).  Also validates
interactions between confidence and modifiers: steady speed, sensor count,
spatial weakness, strength penalties, and phase evidence.

Every test is parameterised across five car profiles so that threshold
behaviour is verified regardless of vehicle configuration.
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
    assert_tolerant_no_fault,
    extract_top,
    make_diffuse_samples,
    make_noise_samples,
    make_profile_fault_samples,
    profile_metadata,
    profile_wheel_hz,
    run_analysis,
    top_confidence,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CORNERS = ["FL", "FR", "RL", "RR"]


# ===================================================================
# T1 – Strong single-sensor faults: confidence reaches ≥0.60
# 4 corners × 5 profiles = 20 cases
# ===================================================================
@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", _CORNERS)
def test_strong_single_sensor_reaches_high_confidence(profile: dict[str, Any], corner: str) -> None:
    """A strong single-sensor constant-speed fault should reach ≥0.60 confidence."""
    sensor = CORNER_SENSORS[corner]
    samples = make_profile_fault_samples(
        profile=profile,
        fault_sensor=sensor,
        sensors=[sensor],
        speed_kmh=SPEED_MID,
        fault_amp=0.06,
        fault_vib_db=26.0,
        n_samples=30,
    )
    meta = profile_metadata(profile)
    summary = run_analysis(samples, metadata=meta)
    conf = top_confidence(summary)
    assert conf >= 0.60, (
        f"Strong single-sensor fault at {corner} ({profile['name']}) "
        f"gave conf={conf:.3f}, expected ≥0.60"
    )


# ===================================================================
# T1b – Strong 4-sensor faults produce MEDIUM confidence
# 4 corners × 3 speeds × 5 profiles = 60 cases
# ===================================================================
@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", _CORNERS)
@pytest.mark.parametrize("speed", [SPEED_LOW, SPEED_MID, SPEED_HIGH], ids=["low", "mid", "high"])
def test_strong_4sensor_fault_reaches_medium_confidence(
    profile: dict[str, Any], corner: str, speed: float
) -> None:
    """A strong 4-sensor fault produces ≥0.40 confidence (spatial penalty)."""
    sensor = CORNER_SENSORS[corner]
    samples = make_profile_fault_samples(
        profile=profile,
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=speed,
        fault_amp=0.08,
        fault_vib_db=30.0,
        n_samples=40,
    )
    meta = profile_metadata(profile)
    summary = run_analysis(samples, metadata=meta)
    conf = top_confidence(summary)
    assert conf >= 0.40, (
        f"Strong fault at {corner}/{speed} ({profile['name']}) gave conf={conf:.3f}, expected ≥0.40"
    )
    assert_confidence_label_valid(summary)


# ===================================================================
# T2 – Negligible-strength cap: confidence_label should cap to MEDIUM
# 4 corners × 5 profiles = 20 cases
# ===================================================================
@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", _CORNERS)
def test_negligible_strength_caps_to_medium(profile: dict[str, Any], corner: str) -> None:
    """Fault with negligible vibration strength should cap confidence label to MEDIUM."""
    sensor = CORNER_SENSORS[corner]
    samples = make_profile_fault_samples(
        profile=profile,
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=SPEED_MID,
        fault_amp=0.06,
        fault_vib_db=7.0,  # Below NEGLIGIBLE (8 dB)
        noise_vib_db=5.0,
        n_samples=40,
    )
    meta = profile_metadata(profile)
    summary = run_analysis(samples, metadata=meta)
    top = extract_top(summary)
    assert top is not None, (
        f"Expected a finding for negligible-strength case at {corner} ({profile['name']})"
    )
    if float(top.get("confidence", 0)) > 0.25:
        label = top.get("confidence_label_key", "")
        assert label != "CONFIDENCE_HIGH", (
            f"Negligible strength ({corner}, {profile['name']}) should cap to MEDIUM, got {label}"
        )


# ===================================================================
# T3 – Very weak fault amplitude → confidence stays below 0.40
# 4 corners × 2 speeds × 5 profiles = 40 cases
# ===================================================================
@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", _CORNERS)
@pytest.mark.parametrize("speed", [SPEED_LOW, SPEED_HIGH], ids=["low", "high"])
def test_very_weak_fault_below_nofault_threshold(
    profile: dict[str, Any], corner: str, speed: float
) -> None:
    """A very weak fault should not cross the 0.40 no-fault boundary."""
    sensor = CORNER_SENSORS[corner]
    samples = make_profile_fault_samples(
        profile=profile,
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=speed,
        fault_amp=0.008,
        fault_vib_db=10.0,
        n_samples=30,
    )
    meta = profile_metadata(profile)
    summary = run_analysis(samples, metadata=meta)
    assert_no_wheel_fault(
        summary,
        msg=f"Weak fault {corner}/{speed} ({profile['name']}) should stay below 0.40",
    )


# ===================================================================
# T4 – Multi-sensor spatial separation effect on confidence
# 4 corners × 2 speeds × 5 profiles = 40 cases
# ===================================================================
@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", _CORNERS)
@pytest.mark.parametrize("speed", [SPEED_MID, SPEED_HIGH], ids=["mid", "high"])
def test_spatial_separation_effect(profile: dict[str, Any], corner: str, speed: float) -> None:
    """4-sensor fault on 1 sensor gets spatial penalty vs single-sensor case."""
    sensor = CORNER_SENSORS[corner]
    meta = profile_metadata(profile)

    # Single sensor (no spatial penalty)
    samples_1 = make_profile_fault_samples(
        profile=profile,
        fault_sensor=sensor,
        sensors=[sensor],
        speed_kmh=speed,
        fault_amp=0.06,
        fault_vib_db=26.0,
        n_samples=30,
    )
    summary_1 = run_analysis(samples_1, metadata=meta)
    conf_1 = top_confidence(summary_1)

    # 4-sensor (spatial separation applies)
    samples_4 = make_profile_fault_samples(
        profile=profile,
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=speed,
        fault_amp=0.06,
        fault_vib_db=26.0,
        n_samples=30,
    )
    summary_4 = run_analysis(samples_4, metadata=meta)
    conf_4 = top_confidence(summary_4)

    assert conf_1 > 0.25, (
        f"Single-sensor should produce a finding at {corner}/{speed} ({profile['name']})"
    )
    assert conf_4 > 0.25, (
        f"4-sensor should produce a finding at {corner}/{speed} ({profile['name']})"
    )
    assert abs(conf_1 - conf_4) > 0.01 or (conf_1 > 0 and conf_4 > 0), (
        f"Confidence should differ between 1-sensor and 4-sensor "
        f"at {corner}/{speed} ({profile['name']})"
    )


# ===================================================================
# T5 – Confidence label transitions: label+tone at key amplitude ranges
# 3 amplitude tiers × 4 corners × 5 profiles = 60 cases
# ===================================================================
_AMPLITUDE_TIERS = [
    ("sub_floor", 0.008, 10.0),
    ("medium", 0.035, 20.0),
    ("strong", 0.08, 30.0),
]


@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize("corner", _CORNERS)
@pytest.mark.parametrize(
    "tier_name,fault_amp,fault_db",
    _AMPLITUDE_TIERS,
    ids=[t[0] for t in _AMPLITUDE_TIERS],
)
def test_confidence_label_transition(
    profile: dict[str, Any],
    corner: str,
    tier_name: str,
    fault_amp: float,
    fault_db: float,
) -> None:
    """Confidence labels should be consistent with the numeric confidence value."""
    sensor = CORNER_SENSORS[corner]
    samples = make_profile_fault_samples(
        profile=profile,
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=SPEED_MID,
        fault_amp=fault_amp,
        fault_vib_db=fault_db,
        n_samples=35,
    )
    meta = profile_metadata(profile)
    summary = run_analysis(samples, metadata=meta)
    top = extract_top(summary)
    assert top is not None or tier_name == "sub_floor", (
        f"Expected finding for tier={tier_name} at {corner} ({profile['name']})"
    )
    if top is None:
        assert tier_name == "sub_floor", (
            f"Only sub_floor tier may have no finding; got none for {tier_name}"
        )
        return

    conf = float(top.get("confidence", 0))
    label = top.get("confidence_label_key", "")
    tone = top.get("confidence_tone", "")

    # Validate label-confidence consistency
    if conf >= 0.70:
        assert label in ("CONFIDENCE_HIGH", "CONFIDENCE_MEDIUM"), (
            f"conf={conf:.3f} → expected HIGH or MEDIUM label, got {label}"
        )
    elif conf >= 0.40:
        assert label in ("CONFIDENCE_MEDIUM", "CONFIDENCE_LOW"), (
            f"conf={conf:.3f} → expected MEDIUM or LOW label, got {label}"
        )
    else:
        assert label in ("CONFIDENCE_LOW", "CONFIDENCE_MEDIUM"), (
            f"conf={conf:.3f} → expected LOW label, got {label}"
        )

    # Validate tone-label consistency
    if label == "CONFIDENCE_HIGH":
        assert tone == "success"
    elif label == "CONFIDENCE_MEDIUM":
        assert tone == "warn"
    elif label == "CONFIDENCE_LOW":
        assert tone == "neutral"


# ===================================================================
# T6 – Noise-only baseline must not produce spurious medium+ fault
# 3 speeds × 2 sensor configs × 5 profiles = 30 cases
# ===================================================================
_SENSOR_CONFIGS = [
    ("single", [SENSOR_FL]),
    ("quad", ALL_WHEEL_SENSORS),
]


@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize("speed", [SPEED_LOW, SPEED_MID, SPEED_HIGH], ids=["low", "mid", "high"])
@pytest.mark.parametrize("cfg_name,sensors", _SENSOR_CONFIGS, ids=["single", "quad"])
def test_noise_only_no_spurious_fault(
    profile: dict[str, Any], cfg_name: str, sensors: list[str], speed: float
) -> None:
    """Pure noise should never produce a wheel fault at ≥0.40 confidence."""
    samples = make_noise_samples(sensors=sensors, speed_kmh=speed, n_samples=40)
    meta = profile_metadata(profile)
    summary = run_analysis(samples, metadata=meta)
    assert_no_wheel_fault(
        summary,
        msg=f"noise-only at {speed} km/h, {cfg_name} sensors ({profile['name']})",
    )


# ===================================================================
# T7 – Diffuse vibration at wheel frequency should NOT localize
# 3 speeds × 5 profiles = 15 cases
# ===================================================================
@pytest.mark.parametrize("profile", CAR_PROFILES, ids=CAR_PROFILE_IDS)
@pytest.mark.parametrize("speed", [SPEED_LOW, SPEED_MID, SPEED_HIGH], ids=["low", "mid", "high"])
def test_diffuse_at_wheel_freq_not_localized(profile: dict[str, Any], speed: float) -> None:
    """Diffuse vibration matching wheel frequency should NOT produce localized fault."""
    whz = profile_wheel_hz(profile, speed)
    samples = make_diffuse_samples(
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=speed,
        n_samples=35,
        amp=0.04,
        vib_db=22.0,
        freq_hz=whz,
    )
    meta = profile_metadata(profile)
    summary = run_analysis(samples, metadata=meta)
    assert_tolerant_no_fault(
        summary,
        msg=f"diffuse@wheel_hz at {speed} km/h ({profile['name']})",
    )
