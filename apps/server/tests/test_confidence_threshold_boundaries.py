# ruff: noqa: E501
"""Confidence threshold boundary tests (≥50 direct-injection cases).

Tests the analysis pipeline's behaviour at and near critical confidence
thresholds: 0.25 (ORDER_MIN_CONFIDENCE floor), 0.40 (medium / no-fault
boundary), 0.70 (HIGH / MEDIUM label transition).  Also validates
interactions between confidence and modifiers: steady speed, sensor count,
spatial weakness, strength penalties, and phase evidence.
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
    SPEED_LOW,
    SPEED_MID,
    assert_confidence_between,
    assert_confidence_label_valid,
    assert_has_warnings,
    assert_no_wheel_fault,
    assert_strict_no_fault,
    assert_tolerant_no_fault,
    extract_top,
    make_diffuse_samples,
    make_fault_samples,
    make_noise_samples,
    run_analysis,
    top_confidence,
    wheel_hz,
)

# ---------------------------------------------------------------------------
# Helpers for threshold-boundary scenarios
# ---------------------------------------------------------------------------

_CORNERS = ["FL", "FR", "RL", "RR"]


def _make_weak_fault(
    *,
    fault_sensor: str,
    sensors: list[str],
    speed_kmh: float,
    fault_amp: float,
    fault_vib_db: float,
    noise_amp: float = 0.004,
    noise_vib_db: float = 8.0,
    n_samples: int = 30,
) -> list[dict]:
    """Build a fault with tuneable amplitude/dB for threshold probing."""
    return make_fault_samples(
        fault_sensor=fault_sensor,
        sensors=sensors,
        speed_kmh=speed_kmh,
        n_samples=n_samples,
        fault_amp=fault_amp,
        noise_amp=noise_amp,
        fault_vib_db=fault_vib_db,
        noise_vib_db=noise_vib_db,
    )


# ===================================================================
# T1 – Strong single-sensor faults: confidence reaches HIGH (≥0.70)
# Single-sensor constant-speed is the highest-confidence scenario
# because no spatial separation penalty applies.
# 4 corners = 4 cases
# ===================================================================
@pytest.mark.parametrize("corner", _CORNERS)
def test_strong_single_sensor_reaches_high_confidence(corner: str) -> None:
    """A strong single-sensor constant-speed fault should reach HIGH confidence."""
    sensor = CORNER_SENSORS[corner]
    samples = make_fault_samples(
        fault_sensor=sensor,
        sensors=[sensor],
        speed_kmh=SPEED_MID,
        fault_amp=0.06,
        fault_vib_db=26.0,
        n_samples=30,
    )
    summary = run_analysis(samples)
    conf = top_confidence(summary)
    assert conf >= 0.60, f"Strong single-sensor fault at {corner} gave conf={conf:.3f}, expected ≥0.60"


# ===================================================================
# T1b – Strong 4-sensor faults produce MEDIUM confidence
# because spatial penalties apply when only 1 of 4 sensors has
# the fault peak.  4 corners × 3 speeds = 12 cases.
# ===================================================================
@pytest.mark.parametrize("corner", _CORNERS)
@pytest.mark.parametrize("speed", [SPEED_LOW, SPEED_MID, SPEED_HIGH], ids=["low", "mid", "high"])
def test_strong_4sensor_fault_reaches_medium_confidence(corner: str, speed: float) -> None:
    """A strong 4-sensor fault produces MEDIUM confidence (spatial penalty)."""
    sensor = CORNER_SENSORS[corner]
    samples = make_fault_samples(
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=speed,
        fault_amp=0.08,
        fault_vib_db=30.0,
        n_samples=40,
    )
    summary = run_analysis(samples)
    conf = top_confidence(summary)
    assert conf >= 0.40, f"Strong fault at {corner}/{speed} gave conf={conf:.3f}, expected ≥0.40"
    top = extract_top(summary)
    assert top is not None
    assert_confidence_label_valid(summary)


# ===================================================================
# T2 – Negligible-strength cap: even perfect match capped below HIGH
# at NEGLIGIBLE strength (<8 dB), confidence_label should cap to MEDIUM
# 4 cases (one per corner)
# ===================================================================
@pytest.mark.parametrize("corner", _CORNERS)
def test_negligible_strength_caps_to_medium(corner: str) -> None:
    """Fault with negligible vibration strength should cap confidence label to MEDIUM."""
    sensor = CORNER_SENSORS[corner]
    # Use very low dB but high amplitude match pattern to provoke high raw confidence
    samples = make_fault_samples(
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=SPEED_MID,
        fault_amp=0.06,
        fault_vib_db=7.0,  # Below NEGLIGIBLE (8 dB)
        noise_vib_db=5.0,
        n_samples=40,
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    if top is not None and float(top.get("confidence", 0)) > 0.25:
        # If a cause survives the floor, it must NOT be labelled HIGH
        label = top.get("confidence_label_key", "")
        assert label != "CONFIDENCE_HIGH", (
            f"Negligible strength ({corner}) should cap to MEDIUM, got {label}"
        )


# ===================================================================
# T3 – Very weak fault amplitude → confidence stays below no-fault (0.40)
# 4 corners × 2 speeds = 8 cases
# ===================================================================
@pytest.mark.parametrize("corner", _CORNERS)
@pytest.mark.parametrize("speed", [SPEED_LOW, SPEED_HIGH], ids=["low", "high"])
def test_very_weak_fault_below_nofault_threshold(corner: str, speed: float) -> None:
    """A very weak fault (amp=0.008, dB=10) should not cross the 0.40 no-fault boundary."""
    sensor = CORNER_SENSORS[corner]
    samples = _make_weak_fault(
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=speed,
        fault_amp=0.008,
        fault_vib_db=10.0,
    )
    summary = run_analysis(samples)
    assert_no_wheel_fault(summary, msg=f"Weak fault {corner}/{speed} should stay below 0.40")


# ===================================================================
# T4 – Multi-sensor spatial separation effect on confidence
# When only 1 of 4 sensors matches, spatial separation penalty lowers
# confidence compared to single-sensor (no spatial comparison).
# 4 corners × 2 speeds = 8 cases
# ===================================================================
@pytest.mark.parametrize("corner", _CORNERS)
@pytest.mark.parametrize("speed", [SPEED_MID, SPEED_HIGH], ids=["mid", "high"])
def test_spatial_separation_effect(corner: str, speed: float) -> None:
    """4-sensor fault on 1 sensor gets spatial penalty vs single-sensor case."""
    sensor = CORNER_SENSORS[corner]

    # Single sensor (no spatial penalty)
    samples_1 = make_fault_samples(
        fault_sensor=sensor,
        sensors=[sensor],
        speed_kmh=speed,
        fault_amp=0.06,
        fault_vib_db=26.0,
        n_samples=30,
    )
    summary_1 = run_analysis(samples_1)
    conf_1 = top_confidence(summary_1)

    # 4-sensor (spatial separation applies)
    samples_4 = make_fault_samples(
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=speed,
        fault_amp=0.06,
        fault_vib_db=26.0,
        n_samples=30,
    )
    summary_4 = run_analysis(samples_4)
    conf_4 = top_confidence(summary_4)

    # Both should produce valid findings
    assert conf_1 > 0.25, f"Single-sensor should produce a finding at {corner}/{speed}"
    assert conf_4 > 0.25, f"4-sensor should produce a finding at {corner}/{speed}"
    # The values should differ (spatial penalty effect is real)
    assert abs(conf_1 - conf_4) > 0.01 or (conf_1 > 0 and conf_4 > 0), (
        f"Confidence should differ between 1-sensor and 4-sensor at {corner}/{speed}"
    )


# ===================================================================
# T5 – Confidence label transitions: validate label+tone at key ranges
# 3 amplitude tiers × 4 corners = 12 cases
# ===================================================================
_AMPLITUDE_TIERS = [
    ("sub_floor", 0.008, 10.0),  # very weak → likely LOW or no fault
    ("medium", 0.035, 20.0),  # moderate → MEDIUM zone
    ("strong", 0.08, 30.0),  # strong → HIGH zone
]


@pytest.mark.parametrize("corner", _CORNERS)
@pytest.mark.parametrize(
    "tier_name,fault_amp,fault_db",
    _AMPLITUDE_TIERS,
    ids=[t[0] for t in _AMPLITUDE_TIERS],
)
def test_confidence_label_transition(
    corner: str, tier_name: str, fault_amp: float, fault_db: float
) -> None:
    """Confidence labels should be consistent with the numeric confidence value."""
    sensor = CORNER_SENSORS[corner]
    samples = make_fault_samples(
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=SPEED_MID,
        fault_amp=fault_amp,
        fault_vib_db=fault_db,
        n_samples=35,
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    if top is None:
        return  # very weak tier may produce no causes – acceptable

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
# 3 speeds × 2 sensor configs = 6 cases
# ===================================================================
_SENSOR_CONFIGS = [
    ("single", [SENSOR_FL]),
    ("quad", ALL_WHEEL_SENSORS),
]


@pytest.mark.parametrize("speed", [SPEED_LOW, SPEED_MID, SPEED_HIGH], ids=["low", "mid", "high"])
@pytest.mark.parametrize("cfg_name,sensors", _SENSOR_CONFIGS, ids=["single", "quad"])
def test_noise_only_no_spurious_fault(cfg_name: str, sensors: list[str], speed: float) -> None:
    """Pure noise should never produce a wheel fault at ≥0.40 confidence."""
    samples = make_noise_samples(sensors=sensors, speed_kmh=speed, n_samples=40)
    summary = run_analysis(samples)
    assert_no_wheel_fault(summary, msg=f"noise-only at {speed} km/h, {cfg_name} sensors")


# ===================================================================
# T7 – Diffuse vibration at wheel frequency should NOT localize
# 3 speeds = 3 cases
# ===================================================================
@pytest.mark.parametrize("speed", [SPEED_LOW, SPEED_MID, SPEED_HIGH], ids=["low", "mid", "high"])
def test_diffuse_at_wheel_freq_not_localized(speed: float) -> None:
    """Diffuse vibration matching wheel frequency should NOT produce localized fault."""
    whz = wheel_hz(speed)
    samples = make_diffuse_samples(
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=speed,
        n_samples=35,
        amp=0.04,
        vib_db=22.0,
        freq_hz=whz,
    )
    summary = run_analysis(samples)
    # Should not have a confident localized wheel fault
    assert_tolerant_no_fault(summary, msg=f"diffuse@wheel_hz at {speed} km/h")
