# ruff: noqa: E501
"""Level C – Single sensor, transient (≥50 direct-injection cases).

Tests the analysis pipeline with exactly ONE sensor and TRANSIENT spikes
present.  Validates that transient events are de-weighted and do not
override persistent fault signals.
"""

from __future__ import annotations

import pytest
from builders import (
    CORNER_SENSORS,
    SENSOR_FL,
    SENSOR_FR,
    SENSOR_RR,
    SPEED_HIGH,
    SPEED_LOW,
    SPEED_MID,
    SPEED_VERY_HIGH,
    assert_confidence_between,
    assert_no_wheel_fault,
    extract_top,
    make_fault_samples,
    make_idle_samples,
    make_noise_samples,
    make_ramp_samples,
    make_transient_samples,
    run_analysis,
    wheel_hz,
)

# ---------------------------------------------------------------------------
# C.1 – Fault + transient at each corner × speed (4×3 = 12 cases)
# Transient should NOT override persistent fault diagnosis
# ---------------------------------------------------------------------------

_CORNERS = ["FL", "FR", "RL", "RR"]
_SPEEDS = [SPEED_LOW, SPEED_MID, SPEED_HIGH]


@pytest.mark.parametrize("corner", _CORNERS)
@pytest.mark.parametrize("speed", _SPEEDS, ids=["low", "mid", "high"])
def test_fault_with_transient_preserves_diagnosis(corner: str, speed: float) -> None:
    """Persistent wheel fault + short transient → fault still detected."""
    sensor = CORNER_SENSORS[corner]
    samples: list[dict] = []
    # Persistent fault
    samples.extend(
        make_fault_samples(
            fault_sensor=sensor,
            sensors=[sensor],
            speed_kmh=speed,
            n_samples=35,
            start_t_s=0,
            fault_amp=0.07,
            fault_vib_db=28.0,
        )
    )
    # Short transient spike mid-run
    samples.extend(
        make_transient_samples(
            sensor=sensor,
            speed_kmh=speed,
            n_samples=3,
            start_t_s=15,
            spike_amp=0.20,
            spike_vib_db=38.0,
        )
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    assert top is not None, f"Lost diagnosis for {corner}@{speed} with transient"
    assert_confidence_between(summary, 0.15, 1.0, msg=f"{corner}@{speed} w/transient")


# ---------------------------------------------------------------------------
# C.2 – Transient only, no fault → no persistent wheel diagnosis (3 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("speed", _SPEEDS, ids=["low", "mid", "high"])
def test_transient_only_no_persistent_fault(speed: float) -> None:
    """Only transient spikes on one sensor → no persistent wheel fault."""
    sensor = SENSOR_FL
    samples: list[dict] = []
    # Road noise baseline
    samples.extend(make_noise_samples(sensors=[sensor], speed_kmh=speed, n_samples=35))
    # Transient spike
    samples.extend(
        make_transient_samples(
            sensor=sensor,
            speed_kmh=speed,
            n_samples=3,
            start_t_s=35,
            spike_amp=0.15,
            spike_vib_db=35.0,
        )
    )
    summary = run_analysis(samples)
    # Should not produce a high-confidence wheel fault
    top = extract_top(summary)
    if top:
        src = (top.get("source") or top.get("suspected_source") or "").lower()
        conf = float(top.get("confidence", 0))
        # If it's a wheel diagnosis, confidence should be very low
        if "wheel" in src:
            assert conf < 0.5, f"Transient-only produced wheel conf={conf} at speed={speed}"


# ---------------------------------------------------------------------------
# C.3 – Multiple transients at different times (4 corners = 4 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corner", _CORNERS)
def test_multiple_transients_no_false_fault(corner: str) -> None:
    """Multiple short transients scattered through recording → no persistent fault."""
    sensor = CORNER_SENSORS[corner]
    samples: list[dict] = []
    samples.extend(make_noise_samples(sensors=[sensor], speed_kmh=SPEED_MID, n_samples=30))
    # Three separate transient bursts
    for t_start in [5, 15, 25]:
        samples.extend(
            make_transient_samples(
                sensor=sensor,
                speed_kmh=SPEED_MID,
                n_samples=2,
                start_t_s=t_start,
                spike_amp=0.12,
                spike_vib_db=33.0,
                spike_freq_hz=45.0 + t_start,
            )
        )
    summary = run_analysis(samples)
    top = extract_top(summary)
    if top:
        conf = float(top.get("confidence", 0))
        src = (top.get("source") or top.get("suspected_source") or "").lower()
        if "wheel" in src:
            assert conf < 0.5, f"Multiple transients → wheel conf={conf} for {corner}"


# ---------------------------------------------------------------------------
# C.4 – Transient amplitude scaling (3 amps × 2 corners = 6 cases)
# ---------------------------------------------------------------------------

_SPIKE_AMPS = [
    ("small", 0.05, 25.0),
    ("medium", 0.15, 35.0),
    ("large", 0.30, 42.0),
]


@pytest.mark.parametrize("corner", ["FL", "RR"])
@pytest.mark.parametrize(
    "label,amp,vdb", _SPIKE_AMPS, ids=["spike_small", "spike_med", "spike_large"]
)
def test_transient_amplitude_deweighting(corner: str, label: str, amp: float, vdb: float) -> None:
    """Persistent fault + transient of varying size → fault still primary."""
    sensor = CORNER_SENSORS[corner]
    samples: list[dict] = []
    samples.extend(
        make_fault_samples(
            fault_sensor=sensor,
            sensors=[sensor],
            speed_kmh=SPEED_MID,
            n_samples=35,
            start_t_s=0,
            fault_amp=0.06,
            fault_vib_db=26.0,
        )
    )
    samples.extend(
        make_transient_samples(
            sensor=sensor,
            speed_kmh=SPEED_MID,
            n_samples=3,
            start_t_s=15,
            spike_amp=amp,
            spike_vib_db=vdb,
        )
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    assert top is not None, f"Lost fault with {label} spike on {corner}"
    assert_confidence_between(summary, 0.15, 1.0, msg=f"{corner} spike={label}")


# ---------------------------------------------------------------------------
# C.5 – Phased onset with transient (4 corners = 4 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corner", _CORNERS)
def test_phased_onset_with_transient(corner: str) -> None:
    """Idle → ramp → fault + transient → fault still detected."""
    sensor = CORNER_SENSORS[corner]
    samples: list[dict] = []
    samples.extend(make_idle_samples(sensors=[sensor], n_samples=8, start_t_s=0))
    samples.extend(
        make_ramp_samples(sensors=[sensor], speed_start=20, speed_end=80, n_samples=12, start_t_s=8)
    )
    samples.extend(
        make_fault_samples(
            fault_sensor=sensor,
            sensors=[sensor],
            speed_kmh=80.0,
            n_samples=30,
            start_t_s=20,
            fault_amp=0.07,
            fault_vib_db=28.0,
        )
    )
    samples.extend(
        make_transient_samples(
            sensor=sensor,
            speed_kmh=80.0,
            n_samples=3,
            start_t_s=30,
            spike_amp=0.18,
            spike_vib_db=36.0,
        )
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    assert top is not None, f"Phased+transient lost {corner}"
    assert_confidence_between(summary, 0.15, 1.0, msg=f"phased+transient {corner}")


# ---------------------------------------------------------------------------
# C.6 – Transient at different frequencies (4 freqs = 4 cases)
# ---------------------------------------------------------------------------

_SPIKE_FREQS = [20.0, 50.0, 100.0, 200.0]


@pytest.mark.parametrize("freq", _SPIKE_FREQS, ids=["20Hz", "50Hz", "100Hz", "200Hz"])
def test_transient_frequency_variation(freq: float) -> None:
    """Transient at various frequencies should all be de-weighted."""
    sensor = SENSOR_FR
    samples: list[dict] = []
    samples.extend(make_noise_samples(sensors=[sensor], speed_kmh=SPEED_MID, n_samples=35))
    samples.extend(
        make_transient_samples(
            sensor=sensor,
            speed_kmh=SPEED_MID,
            n_samples=3,
            start_t_s=35,
            spike_amp=0.15,
            spike_vib_db=35.0,
            spike_freq_hz=freq,
        )
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    if top:
        conf = float(top.get("confidence", 0))
        src = (top.get("source") or top.get("suspected_source") or "").lower()
        if "wheel" in src:
            assert conf < 0.5, f"Transient@{freq}Hz → wheel conf={conf}"


# ---------------------------------------------------------------------------
# C.7 – Long transient burst (wider than typical) (2 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corner", ["RL", "FR"])
def test_long_transient_burst(corner: str) -> None:
    """Longer transient burst (10 samples) within noise → no persistent fault."""
    sensor = CORNER_SENSORS[corner]
    samples: list[dict] = []
    samples.extend(make_noise_samples(sensors=[sensor], speed_kmh=SPEED_MID, n_samples=30))
    samples.extend(
        make_transient_samples(
            sensor=sensor,
            speed_kmh=SPEED_MID,
            n_samples=10,
            start_t_s=30,
            spike_amp=0.12,
            spike_vib_db=33.0,
        )
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    if top:
        conf = float(top.get("confidence", 0))
        src = (top.get("source") or top.get("suspected_source") or "").lower()
        if "wheel" in src:
            assert conf < 0.5, f"Long transient → wheel conf={conf} for {corner}"


# ---------------------------------------------------------------------------
# C.8 – Transient coinciding with wheel frequency (4 corners = 4 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corner", _CORNERS)
def test_transient_at_wheel_freq_no_false_positive(corner: str) -> None:
    """Transient spike at exactly wheel-1x Hz → should not be persistent fault."""
    sensor = CORNER_SENSORS[corner]
    whz = wheel_hz(SPEED_MID)
    samples: list[dict] = []
    samples.extend(make_noise_samples(sensors=[sensor], speed_kmh=SPEED_MID, n_samples=35))
    # Transient at wheel-1x frequency
    samples.extend(
        make_transient_samples(
            sensor=sensor,
            speed_kmh=SPEED_MID,
            n_samples=3,
            start_t_s=35,
            spike_amp=0.18,
            spike_vib_db=36.0,
            spike_freq_hz=whz,
        )
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    if top:
        conf = float(top.get("confidence", 0))
        src = (top.get("source") or top.get("suspected_source") or "").lower()
        if "wheel" in src:
            assert conf < 0.5, f"Transient@wheel_hz → wheel conf={conf} for {corner}"


# ---------------------------------------------------------------------------
# C.9 – Diffuse noise + transient → no fault (2 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("speed", [SPEED_LOW, SPEED_HIGH], ids=["low", "high"])
def test_diffuse_plus_transient_no_fault(speed: float) -> None:
    """Diffuse excitation + transient → no wheel fault."""
    from builders import make_diffuse_samples

    sensor = SENSOR_RR
    samples: list[dict] = []
    samples.extend(make_diffuse_samples(sensors=[sensor], speed_kmh=speed, n_samples=35))
    samples.extend(
        make_transient_samples(
            sensor=sensor,
            speed_kmh=speed,
            n_samples=3,
            start_t_s=35,
            spike_amp=0.15,
            spike_vib_db=35.0,
        )
    )
    summary = run_analysis(samples)
    assert_no_wheel_fault(summary, msg=f"diffuse+transient@{speed}")


# ---------------------------------------------------------------------------
# C.10 – Fault with transient at very high speed (4 corners = 4 cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corner", _CORNERS)
def test_fault_plus_transient_very_high_speed(corner: str) -> None:
    """Fault + transient at 120 km/h → fault still detected."""
    sensor = CORNER_SENSORS[corner]
    samples: list[dict] = []
    samples.extend(
        make_fault_samples(
            fault_sensor=sensor,
            sensors=[sensor],
            speed_kmh=SPEED_VERY_HIGH,
            n_samples=35,
            start_t_s=0,
            fault_amp=0.08,
            fault_vib_db=30.0,
        )
    )
    samples.extend(
        make_transient_samples(
            sensor=sensor,
            speed_kmh=SPEED_VERY_HIGH,
            n_samples=3,
            start_t_s=15,
            spike_amp=0.20,
            spike_vib_db=38.0,
        )
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    assert top is not None, f"Lost fault at 120 + transient for {corner}"
    assert_confidence_between(summary, 0.15, 1.0, msg=f"{corner}@120+transient")


# ---------------------------------------------------------------------------
# C.11 – Transient duration variation (3 durations × 2 corners = 6 cases)
# ---------------------------------------------------------------------------

_SPIKE_DURATIONS = [1, 5, 8]


@pytest.mark.parametrize("corner", ["FL", "RR"])
@pytest.mark.parametrize("n_spike", _SPIKE_DURATIONS, ids=["1sample", "5sample", "8sample"])
def test_transient_duration_variation(corner: str, n_spike: int) -> None:
    """Transient of varying duration alongside persistent fault."""
    sensor = CORNER_SENSORS[corner]
    samples: list[dict] = []
    samples.extend(
        make_fault_samples(
            fault_sensor=sensor,
            sensors=[sensor],
            speed_kmh=SPEED_MID,
            n_samples=35,
            start_t_s=0,
            fault_amp=0.07,
            fault_vib_db=28.0,
        )
    )
    samples.extend(
        make_transient_samples(
            sensor=sensor,
            speed_kmh=SPEED_MID,
            n_samples=n_spike,
            start_t_s=15,
            spike_amp=0.15,
            spike_vib_db=35.0,
        )
    )
    summary = run_analysis(samples)
    top = extract_top(summary)
    assert top is not None, f"Lost fault with {n_spike}-sample transient {corner}"
    assert_confidence_between(summary, 0.15, 1.0, msg=f"{corner} spike_n={n_spike}")
