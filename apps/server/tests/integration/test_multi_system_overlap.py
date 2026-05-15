"""Representative multi-system overlap resolution tests.

Tests how the analysis pipeline resolves overlapping system signatures
(wheel, engine, driveshaft) when multiple vibration sources are present
simultaneously.  Coverage includes:

  MO1 – Engine + wheel both present: representative speed/profile separation.
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
from test_support import (
    ADDITIONAL_CAR_PROFILES,
    ALL_WHEEL_SENSORS,
    CAR_PROFILES,
    CORNER_SENSORS,
    SPEED_HIGH,
    SPEED_LOW,
    SPEED_MID,
    assert_confidence_label_valid,
    assert_diagnosis_contract,
    assert_no_localized_wheel,
    engine_hz,
    extract_top,
    make_engine_order_samples,
    make_sample,
    profile_metadata,
    profile_wheel_hz,
    run_analysis,
    wheel_hz,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Ratio of driveshaft order to wheel-1x order (prop shaft speed ≈ 2.5× wheel)
_DRIVESHAFT_WHEEL_RATIO = 2.5

# Reusable noise-peak sets appended to constructed spectra
_NOISE_SINGLE: list[dict[str, float]] = [{"hz": 142.5, "amp": 0.004}]
_NOISE_DOUBLE: list[dict[str, float]] = [{"hz": 142.5, "amp": 0.004}, {"hz": 87.3, "amp": 0.003}]
_PROFILE_SPAN = [*CAR_PROFILES, *ADDITIONAL_CAR_PROFILES]
_PROFILE_SPAN_IDS = [p["name"] for p in _PROFILE_SPAN]


def _make_overlap_samples(
    *,
    fault_sensor: str,
    sensors: list[str],
    speed_kmh: float,
    wheel_hz_override: float | None = None,
    n_samples: int = 30,
    wheel_amp: float = 0.06,
    bg_peaks: list[dict[str, float]],
    fault_vib_db: float = 26.0,
    noise_vib_db: float = 8.0,
    engine_rpm: float | None = None,
    fault_noise: list[dict[str, float]] | None = None,
    bg_noise: list[dict[str, float]] | None = None,
) -> list[dict[str, Any]]:
    """Build samples with localized wheel fault + background peaks on all sensors.

    *fault_noise* / *bg_noise* default to ``_NOISE_SINGLE`` / ``_NOISE_DOUBLE``
    respectively when ``None``.
    """
    whz = wheel_hz_override if wheel_hz_override is not None else wheel_hz(speed_kmh)
    _fn = fault_noise if fault_noise is not None else _NOISE_SINGLE
    _bn = bg_noise if bg_noise is not None else _NOISE_DOUBLE
    extra_kw: dict[str, Any] = {}
    if engine_rpm is not None:
        extra_kw["engine_rpm"] = engine_rpm
    samples: list[dict[str, Any]] = []
    for i in range(n_samples):
        t = float(i)
        for sensor in sensors:
            if sensor == fault_sensor:
                peaks = (
                    [
                        {"hz": whz, "amp": wheel_amp},
                        {"hz": whz * 2, "amp": wheel_amp * 0.4},
                    ]
                    + bg_peaks
                    + _fn
                )
                vib_db = fault_vib_db
            else:
                peaks = bg_peaks + _bn
                vib_db = noise_vib_db
            samples.append(
                make_sample(
                    t_s=t,
                    speed_kmh=speed_kmh,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=vib_db,
                    strength_floor_amp_g=0.004,
                    **extra_kw,
                ),
            )
    return samples


def _make_engine_plus_wheel_samples(
    *,
    fault_sensor: str,
    sensors: list[str],
    speed_kmh: float = 80.0,
    profile: dict[str, Any] | None = None,
    n_samples: int = 30,
    wheel_amp: float = 0.06,
    engine_amp: float = 0.03,
    wheel_vib_db: float = 26.0,
    noise_vib_db: float = 8.0,
) -> list[dict[str, Any]]:
    """Build samples with both wheel fault (localized) and engine order (all sensors)."""
    if profile is None:
        ehz = engine_hz(speed_kmh)
        whz = None
    else:
        whz = profile_wheel_hz(profile, speed_kmh)
        ehz = whz * profile["final_drive_ratio"] * profile["current_gear_ratio"]
    bg = [{"hz": ehz, "amp": engine_amp}, {"hz": ehz * 2, "amp": engine_amp * 0.5}]
    return _make_overlap_samples(
        fault_sensor=fault_sensor,
        sensors=sensors,
        speed_kmh=speed_kmh,
        wheel_hz_override=whz,
        n_samples=n_samples,
        wheel_amp=wheel_amp,
        bg_peaks=bg,
        fault_vib_db=wheel_vib_db,
        noise_vib_db=noise_vib_db,
        engine_rpm=ehz * 60.0,
    )


def _make_driveshaft_plus_wheel_samples(
    *,
    fault_sensor: str,
    sensors: list[str],
    speed_kmh: float = 60.0,
    profile: dict[str, Any] | None = None,
    n_samples: int = 30,
    wheel_amp: float = 0.06,
    driveshaft_amp: float = 0.04,
    wheel_vib_db: float = 26.0,
    noise_vib_db: float = 8.0,
) -> list[dict[str, Any]]:
    """Build samples with wheel fault + driveshaft-order vibration."""
    whz_val = profile_wheel_hz(profile, speed_kmh) if profile is not None else wheel_hz(speed_kmh)
    dshaft_hz = whz_val * _DRIVESHAFT_WHEEL_RATIO
    bg = [
        {"hz": dshaft_hz, "amp": driveshaft_amp},
        {"hz": dshaft_hz * 2, "amp": driveshaft_amp * 0.4},
    ]
    return _make_overlap_samples(
        fault_sensor=fault_sensor,
        sensors=sensors,
        speed_kmh=speed_kmh,
        wheel_hz_override=whz_val,
        n_samples=n_samples,
        wheel_amp=wheel_amp,
        bg_peaks=bg,
        fault_vib_db=wheel_vib_db,
        noise_vib_db=noise_vib_db,
    )


# ===================================================================
# MO1 – Engine + localized wheel fault: wheel should be detected
# Representative low/high speed and front/rear profile cases.
# ===================================================================
@pytest.mark.parametrize(
    ("corner", "speed", "profile"),
    [
        pytest.param("FL", SPEED_LOW, ADDITIONAL_CAR_PROFILES[0], id="low-front"),
        pytest.param("RR", SPEED_HIGH, ADDITIONAL_CAR_PROFILES[-1], id="high-rear"),
    ],
)
def test_engine_plus_wheel_detects_wheel(
    corner: str,
    speed: float,
    profile: dict[str, Any],
) -> None:
    """When both engine and wheel are present, wheel (localized) should be top finding."""
    sensor = CORNER_SENSORS[corner]
    samples = _make_engine_plus_wheel_samples(
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=speed,
        profile=profile,
        wheel_amp=0.06,
        engine_amp=0.02,
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    assert_diagnosis_contract(
        summary,
        expected_source="wheel",
        expected_sensor=sensor,
        min_confidence=0.01,
        msg=f"engine+wheel at {corner}/{speed}/{profile['name']}",
    )


# ===================================================================
# MO2 – Engine harmonic alias suppression
# When engine confidence is close to wheel, engine should be suppressed.
# Three engine strengths on one representative corner.
# ===================================================================
_ENGINE_STRENGTHS = [
    ("weak_engine", 0.015),  # engine much weaker than wheel
    ("matched_engine", 0.05),  # engine similar to wheel
    ("strong_engine", 0.08),  # engine stronger than wheel
]


@pytest.mark.parametrize(
    ("eng_name", "engine_amp"),
    _ENGINE_STRENGTHS,
    ids=[e[0] for e in _ENGINE_STRENGTHS],
)
def test_engine_alias_suppression(eng_name: str, engine_amp: float) -> None:
    """Engine alias suppression should prevent engine from dominating when wheel is present."""
    sensor = CORNER_SENSORS["FL"]
    samples = _make_engine_plus_wheel_samples(
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=SPEED_MID,
        wheel_amp=0.06,
        engine_amp=engine_amp,
    )
    summary = run_analysis(samples)
    assert_diagnosis_contract(
        summary,
        expected_source="wheel",
        min_confidence=0.01,
        msg=f"engine alias suppression {eng_name}",
    )


# ===================================================================
# MO3 – Driveshaft + wheel overlap
# Representative front/rear and low/mid speed profile cases.
# ===================================================================
@pytest.mark.parametrize(
    ("corner", "speed", "profile"),
    [
        pytest.param("FR", SPEED_LOW, ADDITIONAL_CAR_PROFILES[0], id="low-front"),
        pytest.param("RL", SPEED_MID, ADDITIONAL_CAR_PROFILES[-1], id="mid-rear"),
    ],
)
def test_driveshaft_plus_wheel_overlap(
    corner: str,
    speed: float,
    profile: dict[str, Any],
) -> None:
    """Driveshaft + wheel should not crash; wheel should still be detectable."""
    sensor = CORNER_SENSORS[corner]
    samples = _make_driveshaft_plus_wheel_samples(
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=speed,
        profile=profile,
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    assert_diagnosis_contract(
        summary,
        expected_source="wheel",
        expected_sensor=sensor,
        min_confidence=0.01,
        msg=f"driveshaft+wheel at {corner}/{speed}/{profile['name']}",
    )


# ===================================================================
# MO4 – Three systems simultaneously (wheel + engine + driveshaft-like)
# One front/high and one rear/mid representative.
# ===================================================================
@pytest.mark.parametrize(
    ("corner", "speed"),
    [
        pytest.param("FL", SPEED_HIGH, id="high-front"),
        pytest.param("RR", SPEED_MID, id="mid-rear"),
    ],
)
def test_three_systems_simultaneous(corner: str, speed: float) -> None:
    """Pipeline should handle wheel + engine + driveshaft-like signals without crash."""
    sensor = CORNER_SENSORS[corner]
    whz_val = wheel_hz(speed)
    ehz = engine_hz(speed)
    dshaft_hz = whz_val * _DRIVESHAFT_WHEEL_RATIO
    bg = [
        {"hz": ehz, "amp": 0.025},
        {"hz": ehz * 2, "amp": 0.012},
        {"hz": dshaft_hz, "amp": 0.02},
    ]
    samples = _make_overlap_samples(
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=speed,
        wheel_amp=0.06,
        bg_peaks=bg,
        fault_vib_db=26.0,
        noise_vib_db=10.0,
        engine_rpm=ehz * 60.0,
        fault_noise=[],
        bg_noise=_NOISE_SINGLE,
    )

    summary = run_analysis(samples)
    assert_diagnosis_contract(
        summary,
        expected_source="wheel",
        expected_sensor=sensor,
        min_confidence=0.01,
        msg=f"three-system scenario at {corner}/{speed}",
    )


# ===================================================================
# MO5 – Engine-only (all sensors uniform) → no localized wheel fault
# One moderate mid-speed and one strong high-speed representative.
# ===================================================================
_ENGINE_ONLY_STRENGTHS = [
    ("moderate", 0.04, 22.0),
    ("strong", 0.07, 28.0),
]


@pytest.mark.parametrize(
    ("speed", "eng_name", "engine_amp", "engine_db"),
    [
        pytest.param(SPEED_MID, *_ENGINE_ONLY_STRENGTHS[0], id="mid-moderate"),
        pytest.param(SPEED_HIGH, *_ENGINE_ONLY_STRENGTHS[1], id="high-strong"),
    ],
)
def test_engine_only_no_localized_wheel(
    speed: float,
    eng_name: str,
    engine_amp: float,
    engine_db: float,
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
# Two relative strengths on one limited-layout representative.
# ===================================================================
_RELATIVE_STRENGTHS = [
    ("wheel_dominates", 0.06, 0.02),
    ("wheel_slightly_stronger", 0.04, 0.03),
]


@pytest.mark.parametrize(
    ("strength_name", "wheel_amp", "engine_amp"),
    _RELATIVE_STRENGTHS,
    ids=[s[0] for s in _RELATIVE_STRENGTHS],
)
def test_engine_plus_single_sensor_wheel(
    strength_name: str,
    wheel_amp: float,
    engine_amp: float,
) -> None:
    """Single-sensor overlap should produce a diagnosis without crashing."""
    corner = "FL"
    sensor = CORNER_SENSORS[corner]
    samples = _make_engine_plus_wheel_samples(
        fault_sensor=sensor,
        sensors=[sensor],  # single sensor
        speed_kmh=SPEED_MID,
        wheel_amp=wheel_amp,
        engine_amp=engine_amp,
    )
    summary = run_analysis(samples)
    assert_diagnosis_contract(
        summary,
        min_confidence=0.01,
        msg=(
            f"single-sensor wheel+engine at {corner} ({strength_name}) should produce a diagnosis"
        ),
    )


# ===================================================================
# MO7 – Profile-aware multi-system overlap
# Profile span on one representative corner; corner behavior is covered above.
# ===================================================================
@pytest.mark.parametrize("profile", _PROFILE_SPAN, ids=_PROFILE_SPAN_IDS)
def test_profile_engine_plus_wheel(profile: dict[str, Any]) -> None:
    """Profile-aware engine+wheel should not crash and should produce findings."""
    corner = "FL"
    sensor = CORNER_SENSORS[corner]
    whz = profile_wheel_hz(profile, SPEED_MID)
    ehz = whz * profile["final_drive_ratio"] * profile["current_gear_ratio"]
    bg = [{"hz": ehz, "amp": 0.03}, {"hz": ehz * 2, "amp": 0.015}]
    samples = _make_overlap_samples(
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=SPEED_MID,
        wheel_hz_override=whz,
        wheel_amp=0.06,
        bg_peaks=bg,
        engine_rpm=ehz * 60.0,
        fault_noise=[],
        bg_noise=_NOISE_SINGLE,
    )

    meta = profile_metadata(profile)
    summary = run_analysis(samples, metadata=meta)
    assert_diagnosis_contract(
        summary,
        expected_source="wheel",
        expected_sensor=sensor,
        min_confidence=0.01,
        msg=f"profile {profile['name']} engine+wheel at {corner}",
    )
    # Validate confidence label if above floor
    top = extract_top(summary)
    if top and float(top.get("confidence", 0)) > 0.25:
        assert_confidence_label_valid(summary, msg=f"profile={profile['name']} {corner}")
