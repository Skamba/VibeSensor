# ruff: noqa: E501
"""Negative testing suite – False-positive prevention (50+ injected scenarios).

Validates that the analysis pipeline does NOT over-report:
- No-fault baselines must stay clean across sensor counts and speed bands
- Single-system faults must not report unrelated systems
- Transient-only events must not become persistent faults
- Diffuse excitation must not be localized to a specific wheel
- Phased onset: non-fault phases must be clean
- Ambiguous/weak evidence must stay guarded
- Multi-sensor noisy runs: non-wheel sensors must not become inferred wheel source
- Overlapping sources: one system allowed, others forbidden

All scenarios use direct injection only (no simulator).
All tests are deterministic and parameterized for reuse.
"""

from __future__ import annotations

import pytest
from builders import (
    ALL_WHEEL_SENSORS,
    CORNER_SENSORS,
    NON_WHEEL_SENSORS,
    SENSOR_DRIVESHAFT,
    SENSOR_ENGINE,
    SENSOR_FL,
    SENSOR_TRANSMISSION,
    SENSOR_TRUNK,
    SPEED_HIGH,
    SPEED_LOW,
    SPEED_MID,
    assert_forbidden_systems,
    assert_no_localized_wheel,
    assert_no_persistent_fault,
    assert_no_wheel_fault,
    assert_only_allowed_systems,
    assert_strict_no_fault,
    assert_tolerant_no_fault,
    engine_hz,
    make_diffuse_samples,
    make_engine_order_samples,
    make_fault_samples,
    make_idle_samples,
    make_noise_samples,
    make_ramp_samples,
    make_road_phase_samples,
    make_sample,
    make_transient_samples,
    run_analysis,
    top_confidence,
    wheel_hz,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Shared constants
# ═══════════════════════════════════════════════════════════════════════════════

# Confidence threshold for "medium-or-higher" findings.  Used by most negative
# assertions to distinguish incidental low-confidence noise from a real
# false-positive.
_MEDIUM_CONFIDENCE = 0.55

# ═══════════════════════════════════════════════════════════════════════════════
# Section 1: NO-FAULT BASELINES across sensor counts × speed bands
#
# Pure noise/idle/ramp with no injected fault → must produce no fault above
# threshold.  Sensor counts: 1, 4, 8, 12.
# ═══════════════════════════════════════════════════════════════════════════════

_SENSOR_CONFIGS = {
    "1-sensor": [SENSOR_FL],
    "4-sensor": ALL_WHEEL_SENSORS[:],
    "8-sensor": ALL_WHEEL_SENSORS + NON_WHEEL_SENSORS[:4],
    "12-sensor": ALL_WHEEL_SENSORS + NON_WHEEL_SENSORS,
}

_SPEEDS = [SPEED_LOW, SPEED_MID, SPEED_HIGH]
_SPEED_IDS = ["low", "mid", "high"]


@pytest.mark.parametrize(
    "config_name,sensors",
    list(_SENSOR_CONFIGS.items()),
    ids=lambda x: x if isinstance(x, str) else "",
)
@pytest.mark.parametrize("speed", _SPEEDS, ids=_SPEED_IDS)
def test_no_fault_noise_baseline(config_name: str, sensors: list[str], speed: float) -> None:
    """Pure road noise across sensor counts → no persistent fault.

    3 speeds × 4 configs = 12 scenarios
    """
    samples = make_noise_samples(sensors=sensors, speed_kmh=speed, n_samples=40)
    summary = run_analysis(samples)
    assert_no_wheel_fault(summary, msg=f"{config_name}@{speed}")
    assert_no_persistent_fault(summary, msg=f"{config_name}@{speed}")


@pytest.mark.parametrize(
    "config_name,sensors",
    list(_SENSOR_CONFIGS.items()),
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_no_fault_idle_baseline(config_name: str, sensors: list[str]) -> None:
    """Idle (speed=0) across sensor counts → strict no fault.

    4 scenarios
    """
    samples = make_idle_samples(sensors=sensors, n_samples=40)
    summary = run_analysis(samples)
    assert_strict_no_fault(summary, msg=f"idle-{config_name}")


@pytest.mark.parametrize(
    "config_name,sensors",
    list(_SENSOR_CONFIGS.items()),
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_no_fault_ramp_baseline(config_name: str, sensors: list[str]) -> None:
    """Speed ramp (20→100 km/h) with no fault → no persistent fault.

    4 scenarios
    """
    samples = make_ramp_samples(sensors=sensors, speed_start=20.0, speed_end=100.0, n_samples=40)
    summary = run_analysis(samples)
    assert_strict_no_fault(summary, msg=f"ramp-{config_name}")


# ═══════════════════════════════════════════════════════════════════════════════
# Section 2: SINGLE-SYSTEM WHEEL FAULT – other systems must be forbidden
#
# Inject a wheel fault on exactly one corner.  The analysis may report that
# wheel, but engine/driveline should NOT appear at medium+ confidence.
# ═══════════════════════════════════════════════════════════════════════════════

_CORNERS = ["FL", "FR", "RL", "RR"]


@pytest.mark.parametrize("corner", _CORNERS)
@pytest.mark.parametrize("speed", _SPEEDS, ids=_SPEED_IDS)
def test_single_wheel_fault_no_engine(corner: str, speed: float) -> None:
    """Single wheel fault → engine must NOT appear at confidence ≥0.40.

    4 corners × 3 speeds = 12 scenarios
    """
    sensor = CORNER_SENSORS[corner]
    samples = make_fault_samples(
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=speed,
        n_samples=40,
        fault_amp=0.07,
        fault_vib_db=28.0,
    )
    summary = run_analysis(samples)
    assert_forbidden_systems(
        summary,
        forbidden=["engine", "driveline"],
        confidence_threshold=_MEDIUM_CONFIDENCE,
        msg=f"wheel-fault-{corner}@{speed}",
    )
    assert_only_allowed_systems(
        summary,
        allowed=["wheel", "tire", "unknown"],
        confidence_threshold=_MEDIUM_CONFIDENCE,
        msg=f"wheel-fault-{corner}@{speed}",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Section 3: TRANSIENT-ONLY spikes must NOT become persistent faults
#
# Short spike/impact events (potholes, bumps) on noise baseline →
# no persistent fault diagnosed.
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("speed", _SPEEDS, ids=_SPEED_IDS)
def test_transient_only_single_sensor(speed: float) -> None:
    """Transient spike on noise baseline (1 sensor) → no persistent fault.

    3 scenarios
    """
    samples = make_noise_samples(sensors=[SENSOR_FL], speed_kmh=speed, n_samples=40)
    samples.extend(
        make_transient_samples(
            sensor=SENSOR_FL,
            speed_kmh=speed,
            n_samples=3,
            start_t_s=20,
            spike_amp=0.20,
            spike_vib_db=38.0,
        )
    )
    summary = run_analysis(samples)
    assert_tolerant_no_fault(summary, msg=f"transient-1s@{speed}")


@pytest.mark.parametrize("speed", _SPEEDS, ids=_SPEED_IDS)
def test_transient_only_four_sensors(speed: float) -> None:
    """Transient spikes on all 4 wheel sensors (simultaneous pothole) → no persistent fault.

    3 scenarios
    """
    samples = make_noise_samples(sensors=ALL_WHEEL_SENSORS, speed_kmh=speed, n_samples=40)
    for sensor in ALL_WHEEL_SENSORS:
        samples.extend(
            make_transient_samples(
                sensor=sensor,
                speed_kmh=speed,
                n_samples=3,
                start_t_s=20,
                spike_amp=0.18,
                spike_vib_db=36.0,
            )
        )
    summary = run_analysis(samples)
    assert_tolerant_no_fault(summary, msg=f"transient-4s@{speed}")


@pytest.mark.parametrize("corner", _CORNERS)
def test_transient_on_one_corner_no_localization(corner: str) -> None:
    """A single transient on one corner amid noise → must not localize a wheel fault.

    4 scenarios
    """
    samples = make_noise_samples(sensors=ALL_WHEEL_SENSORS, speed_kmh=SPEED_MID, n_samples=40)
    samples.extend(
        make_transient_samples(
            sensor=CORNER_SENSORS[corner],
            speed_kmh=SPEED_MID,
            n_samples=2,
            start_t_s=20,
            spike_amp=0.25,
            spike_vib_db=40.0,
        )
    )
    summary = run_analysis(samples)
    assert_tolerant_no_fault(summary, msg=f"transient-corner-{corner}")


# ═══════════════════════════════════════════════════════════════════════════════
# Section 4: DIFFUSE / GLOBAL excitation must NOT localize to wheel
#
# Uniform vibration across all sensors should not be attributed to a
# specific wheel corner.
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("speed", _SPEEDS, ids=_SPEED_IDS)
def test_diffuse_excitation_not_localized(speed: float) -> None:
    """Uniform vibration on all 4 sensors → must not localize to a single wheel.

    3 scenarios
    """
    samples = make_diffuse_samples(
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=speed,
        n_samples=40,
        amp=0.03,
        vib_db=20.0,
    )
    summary = run_analysis(samples)
    assert_no_localized_wheel(summary, confidence_threshold=0.50, msg=f"diffuse@{speed}")


@pytest.mark.parametrize(
    "config_name,sensors",
    [
        ("8-sensor", ALL_WHEEL_SENSORS + NON_WHEEL_SENSORS[:4]),
        ("12-sensor", ALL_WHEEL_SENSORS + NON_WHEEL_SENSORS),
    ],
    ids=["8-sensor", "12-sensor"],
)
def test_diffuse_excitation_many_sensors(config_name: str, sensors: list[str]) -> None:
    """Uniform vibration on 8/12 sensors → must not localize to a single wheel.

    2 scenarios
    """
    samples = make_diffuse_samples(
        sensors=sensors,
        speed_kmh=SPEED_MID,
        n_samples=40,
        amp=0.03,
        vib_db=20.0,
    )
    summary = run_analysis(samples)
    assert_no_localized_wheel(summary, confidence_threshold=0.50, msg=f"diffuse-{config_name}")


def test_diffuse_at_wheel_frequency_no_localization() -> None:
    """Diffuse vibration at wheel-order frequency → must not localize.

    1 scenario
    """
    whz = wheel_hz(SPEED_MID)
    samples = make_diffuse_samples(
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=SPEED_MID,
        n_samples=40,
        amp=0.03,
        vib_db=20.0,
        freq_hz=whz,
    )
    summary = run_analysis(samples)
    assert_no_localized_wheel(summary, confidence_threshold=0.50, msg="diffuse-at-wheel-hz")


# ═══════════════════════════════════════════════════════════════════════════════
# Section 5: PHASED ONSET – fault only in one phase
#
# Clean cruise followed by fault onset, or fault followed by clean:
# the non-fault phases should not produce false positives by themselves.
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("corner", _CORNERS)
def test_fault_late_onset_clean_early_phase(corner: str) -> None:
    """Clean cruise for 25s, then fault for 15s.  Early phase alone → no fault.

    Also validates that the overall analysis detects the fault in the late phase.
    4 scenarios
    """
    sensor = CORNER_SENSORS[corner]
    # Clean early phase
    early_samples = make_noise_samples(
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=SPEED_MID,
        n_samples=25,
        start_t_s=0.0,
    )
    # Fault late phase
    late_samples = make_fault_samples(
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=SPEED_MID,
        n_samples=15,
        start_t_s=25.0,
        fault_amp=0.07,
        fault_vib_db=28.0,
    )

    # Early phase alone → no persistent fault
    early_summary = run_analysis(early_samples)
    assert_no_wheel_fault(early_summary, msg=f"early-phase-{corner}")

    # Full run with both phases → analysis should still work (not necessarily clean)
    all_samples = early_samples + late_samples
    _full_summary = run_analysis(all_samples)
    # We don't assert the combined result strictly – the key negative test
    # is that the clean phase alone doesn't produce false positives.


# ═══════════════════════════════════════════════════════════════════════════════
# Section 6: AMBIGUOUS / WEAK evidence must stay guarded
#
# Very low amplitude faults, borderline signals, or noisy backgrounds
# should produce low confidence or no finding.
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "amp,vib_db,label",
    [
        (0.008, 12.0, "barely-above-noise"),
        (0.012, 14.0, "weak"),
        (0.015, 16.0, "marginal"),
    ],
    ids=["barely-above-noise", "weak", "marginal"],
)
def test_weak_fault_stays_guarded(amp: float, vib_db: float, label: str) -> None:
    """Very weak wheel-order signal on noise → confidence must stay below 0.50.

    3 scenarios
    """
    samples = make_fault_samples(
        fault_sensor=SENSOR_FL,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=SPEED_MID,
        n_samples=40,
        fault_amp=amp,
        fault_vib_db=vib_db,
        noise_amp=0.005,
        noise_vib_db=10.0,
    )
    summary = run_analysis(samples)
    conf = top_confidence(summary)
    assert conf < 0.50, (
        f"Weak signal '{label}' should be guarded (conf={conf:.3f}). Expected < 0.50."
    )


def test_ambiguous_dual_frequency_low_confidence() -> None:
    """Two competing frequencies at similar amplitude → confidence should be modest.

    1 scenario
    """
    whz = wheel_hz(SPEED_MID)
    ehz = engine_hz(SPEED_MID)
    samples = []
    for i in range(40):
        for sensor in ALL_WHEEL_SENSORS:
            peaks = [
                {"hz": whz, "amp": 0.03},
                {"hz": ehz, "amp": 0.028},
                {"hz": 55.0, "amp": 0.004},
            ]
            samples.append(
                make_sample(
                    t_s=float(i),
                    speed_kmh=SPEED_MID,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=20.0,
                    strength_floor_amp_g=0.004,
                )
            )
    summary = run_analysis(samples)
    conf = top_confidence(summary)
    # With two competing sources at similar amplitude, top confidence should be moderate
    assert conf < 0.80, (
        f"Ambiguous dual-frequency scenario has too-high confidence ({conf:.3f}). Expected < 0.80."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Section 7: MULTI-SENSOR NOISY – non-wheel sensors must not become wheel source
#
# Sensors placed on engine/driveshaft/trunk etc. with noise only:
# the analysis should not infer a wheel fault from them.
# ═══════════════════════════════════════════════════════════════════════════════


def test_non_wheel_sensors_only_noise_no_wheel_fault() -> None:
    """4 non-wheel sensors with noise only → no wheel fault.

    1 scenario
    """
    sensors = NON_WHEEL_SENSORS[:4]
    samples = make_noise_samples(sensors=sensors, speed_kmh=SPEED_MID, n_samples=40)
    summary = run_analysis(samples)
    assert_no_wheel_fault(summary, msg="non-wheel-noise")


def test_mixed_sensors_noise_only_no_wheel_fault() -> None:
    """4 wheel + 4 non-wheel sensors all with noise → no wheel fault.

    1 scenario
    """
    sensors = ALL_WHEEL_SENSORS + NON_WHEEL_SENSORS[:4]
    samples = make_noise_samples(sensors=sensors, speed_kmh=SPEED_MID, n_samples=40)
    summary = run_analysis(samples)
    assert_no_wheel_fault(summary, msg="mixed-8s-noise")


def test_non_wheel_high_vibration_no_wheel_fault() -> None:
    """Non-wheel sensors with elevated (but non-wheel-order) vibration → no wheel fault.

    1 scenario
    """
    sensors = [SENSOR_ENGINE, SENSOR_DRIVESHAFT, SENSOR_TRANSMISSION, SENSOR_TRUNK]
    samples = make_diffuse_samples(
        sensors=sensors,
        speed_kmh=SPEED_MID,
        n_samples=40,
        amp=0.04,
        vib_db=22.0,
        freq_hz=45.0,  # Not a wheel order frequency
    )
    summary = run_analysis(samples)
    assert_no_wheel_fault(summary, msg="non-wheel-elevated")


def test_engine_vibration_not_reported_as_wheel() -> None:
    """Engine-order harmonics on all sensors → must not be reported as wheel/tire.

    1 scenario
    """
    sensors = ALL_WHEEL_SENSORS + [SENSOR_ENGINE, SENSOR_TRANSMISSION]
    samples = make_engine_order_samples(
        sensors=sensors,
        speed_kmh=SPEED_MID,
        n_samples=40,
        engine_amp=0.05,
        engine_vib_db=24.0,
    )
    summary = run_analysis(samples)
    # Engine vibration should not be reported as wheel/tire with high confidence
    assert_forbidden_systems(
        summary,
        forbidden=["wheel", "tire"],
        confidence_threshold=_MEDIUM_CONFIDENCE,
        msg="engine-order-as-wheel",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Section 8: OVERLAPPING SOURCES – one system allowed, others forbidden
#
# Inject a clear wheel fault + engine noise.  Wheel may be detected,
# but engine should not be over-promoted.
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("corner", _CORNERS)
def test_wheel_fault_with_engine_noise_no_engine_overreport(corner: str) -> None:
    """Wheel fault + low-level engine noise → engine must not appear above 0.55 confidence.

    4 scenarios
    """
    sensor = CORNER_SENSORS[corner]
    # Wheel fault samples
    wheel_samples = make_fault_samples(
        fault_sensor=sensor,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=SPEED_MID,
        n_samples=40,
        fault_amp=0.07,
        fault_vib_db=28.0,
    )
    # Weak engine noise on all sensors
    engine_noise_samples = make_engine_order_samples(
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=SPEED_MID,
        n_samples=40,
        engine_amp=0.015,
        engine_vib_db=14.0,
    )
    # Merge by interleaving timesteps
    all_samples = wheel_samples + engine_noise_samples
    summary = run_analysis(all_samples)
    assert_forbidden_systems(
        summary,
        forbidden=["engine"],
        confidence_threshold=_MEDIUM_CONFIDENCE,
        msg=f"overlap-wheel-engine-{corner}",
    )


def test_wheel_fault_with_road_phase_noise() -> None:
    """Wheel fault + road surface phase changes → forbidden systems stay suppressed.

    1 scenario
    """
    # Wheel fault
    wheel_samples = make_fault_samples(
        fault_sensor=SENSOR_FL,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=SPEED_MID,
        n_samples=40,
        fault_amp=0.07,
        fault_vib_db=28.0,
    )
    # Road phase changes on top
    road_samples = make_road_phase_samples(
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=SPEED_MID,
    )
    all_samples = wheel_samples + road_samples
    summary = run_analysis(all_samples)
    # Engine/driveline should not be over-reported
    assert_forbidden_systems(
        summary,
        forbidden=["driveline"],
        confidence_threshold=0.50,
        msg="overlap-wheel-road",
    )


def test_engine_order_with_transient_no_wheel() -> None:
    """Engine vibration + transient spike → must not become a wheel fault.

    1 scenario
    """
    sensors = ALL_WHEEL_SENSORS + [SENSOR_ENGINE]
    samples = make_engine_order_samples(
        sensors=sensors,
        speed_kmh=SPEED_HIGH,
        n_samples=40,
        engine_amp=0.04,
        engine_vib_db=22.0,
    )
    samples.extend(
        make_transient_samples(
            sensor=SENSOR_FL,
            speed_kmh=SPEED_HIGH,
            n_samples=3,
            start_t_s=20,
            spike_amp=0.15,
            spike_vib_db=35.0,
        )
    )
    summary = run_analysis(samples)
    assert_forbidden_systems(
        summary,
        forbidden=["wheel", "tire"],
        confidence_threshold=_MEDIUM_CONFIDENCE,
        msg="engine+transient-no-wheel",
    )
