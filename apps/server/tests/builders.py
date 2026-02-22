# ruff: noqa: E501
"""Shared synthetic data builders for the layered test pyramid.

These builders generate deterministic sensor data that feeds the analysis
pipeline directly (bypassing ingestion/simulator) for levels 2–5 of the
test pyramid.

Public API
----------
- ``standard_metadata``  – canonical run metadata dict
- ``wheel_hz``           – wheel-1x frequency at a given speed
- ``make_sample``        – single JSONL-style sample dict
- ``make_noise_samples`` – broadband road-noise baseline
- ``make_fault_samples`` – wheel-order fault at one sensor/corner
- ``make_transient_samples`` – short spike/impact events
- ``make_diffuse_samples``  – uniform cross-sensor excitation
- ``make_idle_samples``     – stationary/idle phase
- ``make_ramp_samples``     – speed-ramp (acceleration/deceleration)
- ``run_analysis``       – convenience wrapper around ``summarize_run_data``
- ``extract_top``        – pull the first top-cause from a summary
"""

from __future__ import annotations

import hashlib
from typing import Any

from vibesensor_core.strength_bands import bucket_for_strength

from vibesensor.analysis_settings import (
    DEFAULT_ANALYSIS_SETTINGS,
    tire_circumference_m_from_spec,
    wheel_hz_from_speed_kmh,
)
from vibesensor.report.summary import summarize_run_data

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TIRE_CIRC = tire_circumference_m_from_spec(
    DEFAULT_ANALYSIS_SETTINGS["tire_width_mm"],
    DEFAULT_ANALYSIS_SETTINGS["tire_aspect_pct"],
    DEFAULT_ANALYSIS_SETTINGS["rim_in"],
)
FINAL_DRIVE = DEFAULT_ANALYSIS_SETTINGS["final_drive_ratio"]
GEAR_RATIO = DEFAULT_ANALYSIS_SETTINGS["current_gear_ratio"]

# Canonical sensor names / corners
SENSOR_FL = "front-left"
SENSOR_FR = "front-right"
SENSOR_RL = "rear-left"
SENSOR_RR = "rear-right"
ALL_WHEEL_SENSORS = [SENSOR_FL, SENSOR_FR, SENSOR_RL, SENSOR_RR]

# Non-wheel sensor names for multi-sensor scenarios
SENSOR_ENGINE = "engine-bay"
SENSOR_DRIVESHAFT = "driveshaft-tunnel"
SENSOR_TRANSMISSION = "transmission"
SENSOR_TRUNK = "trunk"
SENSOR_DRIVER_SEAT = "driver-seat"
SENSOR_FRONT_SUBFRAME = "front-subframe"
SENSOR_REAR_SUBFRAME = "rear-subframe"
SENSOR_PASSENGER_SEAT = "front-passenger-seat"

NON_WHEEL_SENSORS = [
    SENSOR_ENGINE,
    SENSOR_DRIVESHAFT,
    SENSOR_TRANSMISSION,
    SENSOR_TRUNK,
    SENSOR_DRIVER_SEAT,
    SENSOR_FRONT_SUBFRAME,
    SENSOR_REAR_SUBFRAME,
    SENSOR_PASSENGER_SEAT,
]

# Corner code → canonical sensor name
CORNER_SENSORS = {
    "FL": SENSOR_FL,
    "FR": SENSOR_FR,
    "RL": SENSOR_RL,
    "RR": SENSOR_RR,
}

# Speed bands
SPEED_LOW = 30.0  # km/h
SPEED_MID = 60.0
SPEED_HIGH = 100.0
SPEED_VERY_HIGH = 120.0


# ---------------------------------------------------------------------------
# Stable deterministic hash (replaces Python hash() which varies per process)
# ---------------------------------------------------------------------------


def _stable_hash(s: str) -> int:
    """Return a stable positive integer derived from *s* (deterministic across runs)."""
    return int(hashlib.md5(s.encode()).hexdigest(), 16)


# ---------------------------------------------------------------------------
# Metadata builder
# ---------------------------------------------------------------------------


def standard_metadata(*, language: str = "en", **overrides: Any) -> dict[str, Any]:
    """Return a minimal valid run-metadata dict."""
    meta: dict[str, Any] = {
        "tire_circumference_m": TIRE_CIRC,
        "raw_sample_rate_hz": 800.0,
        "final_drive_ratio": FINAL_DRIVE,
        "current_gear_ratio": GEAR_RATIO,
        "sensor_model": "ADXL345",
        "units": {"accel_x_g": "g"},
        "language": language,
    }
    meta.update(overrides)
    return meta


# ---------------------------------------------------------------------------
# Frequency helpers
# ---------------------------------------------------------------------------


def wheel_hz(speed_kmh: float) -> float:
    """Compute wheel-1x frequency for *speed_kmh*."""
    hz = wheel_hz_from_speed_kmh(speed_kmh, TIRE_CIRC)
    assert hz is not None and hz > 0
    return hz


def engine_hz(
    speed_kmh: float, gear_ratio: float = GEAR_RATIO, final_drive: float = FINAL_DRIVE
) -> float:
    """Rough engine-1x Hz from speed (2-stroke assumption for simplicity)."""
    whz = wheel_hz(speed_kmh)
    return whz * final_drive * gear_ratio


# ---------------------------------------------------------------------------
# Single-sample builder
# ---------------------------------------------------------------------------


def make_sample(
    *,
    t_s: float,
    speed_kmh: float,
    client_name: str,
    top_peaks: list[dict[str, float]] | None = None,
    vibration_strength_db: float = 15.0,
    strength_floor_amp_g: float = 0.003,
    accel_x_g: float = 0.02,
    accel_y_g: float = 0.02,
    accel_z_g: float = 0.10,
    engine_rpm: float | None = None,
    dominant_freq_hz: float | None = None,
    location: str = "",
    client_id: str | None = None,
    strength_peak_amp_g: float | None = None,
) -> dict[str, Any]:
    """Build a single JSONL-style sensor sample dict."""
    sample: dict[str, Any] = {
        "t_s": t_s,
        "speed_kmh": speed_kmh,
        "accel_x_g": accel_x_g,
        "accel_y_g": accel_y_g,
        "accel_z_g": accel_z_g,
        "vibration_strength_db": vibration_strength_db,
        "strength_bucket": bucket_for_strength(vibration_strength_db),
        "strength_floor_amp_g": strength_floor_amp_g,
        "client_name": client_name,
        "client_id": client_id or f"sensor-{client_name}",
        "top_peaks": top_peaks or [],
        "frames_dropped_total": 0,
        "queue_overflow_drops": 0,
    }
    if engine_rpm is not None:
        sample["engine_rpm"] = engine_rpm
    if dominant_freq_hz is not None:
        sample["dominant_freq_hz"] = dominant_freq_hz
    if location:
        sample["location"] = location
    if strength_peak_amp_g is not None:
        sample["strength_peak_amp_g"] = strength_peak_amp_g
    return sample


# ---------------------------------------------------------------------------
# Bulk sample builders
# ---------------------------------------------------------------------------


def make_noise_samples(
    *,
    sensors: list[str],
    speed_kmh: float = 60.0,
    n_samples: int = 30,
    dt_s: float = 1.0,
    start_t_s: float = 0.0,
    noise_amp: float = 0.004,
    vib_db: float = 10.0,
) -> list[dict[str, Any]]:
    """Generate broadband road-noise baseline on all *sensors*."""
    samples: list[dict[str, Any]] = []
    for i in range(n_samples):
        t = start_t_s + i * dt_s
        for sensor in sensors:
            # Deterministic but varied noise peaks per sensor
            offset = _stable_hash(sensor) % 20
            peaks = [
                {"hz": 15.0 + offset, "amp": noise_amp},
                {"hz": 34.0, "amp": noise_amp * 0.7},
                {"hz": 88.0, "amp": noise_amp * 0.5},
            ]
            samples.append(
                make_sample(
                    t_s=t,
                    speed_kmh=speed_kmh,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=vib_db,
                    strength_floor_amp_g=noise_amp,
                )
            )
    return samples


def make_fault_samples(
    *,
    fault_sensor: str,
    sensors: list[str],
    speed_kmh: float = 80.0,
    n_samples: int = 30,
    dt_s: float = 1.0,
    start_t_s: float = 0.0,
    fault_amp: float = 0.06,
    noise_amp: float = 0.004,
    fault_vib_db: float = 26.0,
    noise_vib_db: float = 8.0,
    add_wheel_2x: bool = True,
    add_wheel_3x: bool = False,
    transfer_fraction: float = 0.0,
) -> list[dict[str, Any]]:
    """Generate wheel-order fault on *fault_sensor* with noise on others.

    Parameters
    ----------
    transfer_fraction:
        Fraction of fault amplitude leaked to non-fault sensors (0.0–1.0).
        Simulates vibration transfer paths in the vehicle.
    """
    samples: list[dict[str, Any]] = []
    whz = wheel_hz(speed_kmh)
    for i in range(n_samples):
        t = start_t_s + i * dt_s
        for sensor in sensors:
            if sensor == fault_sensor:
                peaks: list[dict[str, float]] = [{"hz": whz, "amp": fault_amp}]
                if add_wheel_2x:
                    peaks.append({"hz": whz * 2, "amp": fault_amp * 0.4})
                if add_wheel_3x:
                    peaks.append({"hz": whz * 3, "amp": fault_amp * 0.2})
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
                other_peaks: list[dict[str, float]] = [
                    {"hz": 142.5, "amp": noise_amp},
                    {"hz": 87.3, "amp": noise_amp * 0.8},
                ]
                if transfer_fraction > 0:
                    other_peaks.insert(
                        0,
                        {"hz": whz, "amp": fault_amp * transfer_fraction},
                    )
                samples.append(
                    make_sample(
                        t_s=t,
                        speed_kmh=speed_kmh,
                        client_name=sensor,
                        top_peaks=other_peaks,
                        vibration_strength_db=noise_vib_db,
                        strength_floor_amp_g=noise_amp,
                    )
                )
    return samples


def make_transient_samples(
    *,
    sensor: str,
    speed_kmh: float = 60.0,
    n_samples: int = 3,
    dt_s: float = 1.0,
    start_t_s: float = 0.0,
    spike_amp: float = 0.15,
    spike_vib_db: float = 35.0,
    spike_freq_hz: float = 50.0,
) -> list[dict[str, Any]]:
    """Generate short transient spike/impact on one sensor.

    The spike occupies *n_samples* timesteps (short burst, high amplitude).
    """
    samples: list[dict[str, Any]] = []
    for i in range(n_samples):
        t = start_t_s + i * dt_s
        peaks = [
            {"hz": spike_freq_hz, "amp": spike_amp},
            {"hz": spike_freq_hz * 2.3, "amp": spike_amp * 0.6},
        ]
        samples.append(
            make_sample(
                t_s=t,
                speed_kmh=speed_kmh,
                client_name=sensor,
                top_peaks=peaks,
                vibration_strength_db=spike_vib_db,
                strength_floor_amp_g=0.003,
            )
        )
    return samples


def make_diffuse_samples(
    *,
    sensors: list[str],
    speed_kmh: float = 80.0,
    n_samples: int = 30,
    dt_s: float = 1.0,
    start_t_s: float = 0.0,
    amp: float = 0.03,
    vib_db: float = 20.0,
    freq_hz: float = 25.0,
) -> list[dict[str, Any]]:
    """Generate uniform cross-sensor excitation (diffuse vibration).

    All sensors see the *same* dominant frequency at similar amplitude.
    """
    samples: list[dict[str, Any]] = []
    for i in range(n_samples):
        t = start_t_s + i * dt_s
        for sensor in sensors:
            # Small per-sensor jitter for realism (stable across runs)
            jitter = (_stable_hash(sensor + str(i)) % 10) * 0.001
            peaks = [
                {"hz": freq_hz, "amp": amp + jitter},
                {"hz": freq_hz * 2.0, "amp": (amp + jitter) * 0.3},
            ]
            samples.append(
                make_sample(
                    t_s=t,
                    speed_kmh=speed_kmh,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=vib_db,
                    strength_floor_amp_g=0.003,
                )
            )
    return samples


def make_idle_samples(
    *,
    sensors: list[str],
    n_samples: int = 10,
    dt_s: float = 1.0,
    start_t_s: float = 0.0,
    noise_amp: float = 0.003,
) -> list[dict[str, Any]]:
    """Generate stationary/idle samples (speed=0, low noise)."""
    samples: list[dict[str, Any]] = []
    for i in range(n_samples):
        t = start_t_s + i * dt_s
        for sensor in sensors:
            peaks = [
                {"hz": 12.5 + (_stable_hash(sensor) % 10), "amp": noise_amp},
                {"hz": 25.0, "amp": noise_amp * 0.5},
            ]
            samples.append(
                make_sample(
                    t_s=t,
                    speed_kmh=0.0,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=6.0,
                    strength_floor_amp_g=noise_amp,
                )
            )
    return samples


def make_ramp_samples(
    *,
    sensors: list[str],
    speed_start: float = 20.0,
    speed_end: float = 100.0,
    n_samples: int = 20,
    dt_s: float = 1.0,
    start_t_s: float = 0.0,
    noise_amp: float = 0.004,
    vib_db: float = 10.0,
) -> list[dict[str, Any]]:
    """Generate speed ramp (acceleration or deceleration)."""
    samples: list[dict[str, Any]] = []
    for i in range(n_samples):
        t = start_t_s + i * dt_s
        ratio = i / max(1, n_samples - 1)
        speed = speed_start + (speed_end - speed_start) * ratio
        for sensor in sensors:
            peaks = [
                {"hz": 15.0 + (_stable_hash(sensor) % 20), "amp": noise_amp},
                {"hz": 60.0, "amp": noise_amp * 0.6},
            ]
            samples.append(
                make_sample(
                    t_s=t,
                    speed_kmh=speed,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=vib_db,
                    strength_floor_amp_g=noise_amp,
                )
            )
    return samples


def make_speed_sweep_fault_samples(
    *,
    fault_sensor: str,
    sensors: list[str],
    speed_start: float = 40.0,
    speed_end: float = 100.0,
    n_steps: int = 5,
    samples_per_step: int = 10,
    dt_s: float = 1.0,
    start_t_s: float = 0.0,
    fault_amp: float = 0.06,
    noise_amp: float = 0.004,
    fault_vib_db: float = 26.0,
    noise_vib_db: float = 8.0,
) -> list[dict[str, Any]]:
    """Generate fault samples across a sweep of speeds."""
    samples: list[dict[str, Any]] = []
    t = start_t_s
    for step in range(n_steps):
        ratio = step / max(1, n_steps - 1)
        speed = speed_start + (speed_end - speed_start) * ratio
        samples.extend(
            make_fault_samples(
                fault_sensor=fault_sensor,
                sensors=sensors,
                speed_kmh=speed,
                n_samples=samples_per_step,
                dt_s=dt_s,
                start_t_s=t,
                fault_amp=fault_amp,
                noise_amp=noise_amp,
                fault_vib_db=fault_vib_db,
                noise_vib_db=noise_vib_db,
            )
        )
        t += samples_per_step * dt_s
    return samples


# ---------------------------------------------------------------------------
# Analysis runner
# ---------------------------------------------------------------------------


def run_analysis(
    samples: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
    **meta_overrides: Any,
) -> dict[str, Any]:
    """Run the full analysis pipeline on *samples* and return the summary."""
    meta = metadata or standard_metadata(**meta_overrides)
    return summarize_run_data(meta, samples, lang=meta.get("language", "en"))


def extract_top(summary: dict[str, Any]) -> dict[str, Any] | None:
    """Return the first top-cause dict from a summary, or None."""
    causes = summary.get("top_causes") or []
    return causes[0] if causes else None


def extract_top_n(summary: dict[str, Any], n: int = 3) -> list[dict[str, Any]]:
    """Return up to *n* top-cause dicts from a summary."""
    return (summary.get("top_causes") or [])[:n]


def top_corner_label(summary: dict[str, Any]) -> str | None:
    """Return the human-readable location/corner from the top cause."""
    top = extract_top(summary)
    if not top:
        return None
    return top.get("strongest_location") or top.get("location_hotspot") or top.get("suspected_source")


def top_confidence(summary: dict[str, Any]) -> float:
    """Return the confidence (0–1) of the top cause, or 0.0 if none."""
    top = extract_top(summary)
    return float(top.get("confidence", 0.0)) if top else 0.0


def has_no_fault(summary: dict[str, Any]) -> bool:
    """Return True if analysis found no significant fault."""
    causes = summary.get("top_causes") or []
    if not causes:
        return True
    # All causes have very low confidence
    return all(float(c.get("confidence", 0)) < 0.15 for c in causes)


def _corner_in_label(label: str | None, corner: str) -> bool:
    """Check if a corner code (FL/FR/RL/RR) or location matches the label."""
    if not label:
        return False
    label_lower = label.lower()
    corner_map = {
        "FL": ("front left", "front-left", "fl"),
        "FR": ("front right", "front-right", "fr"),
        "RL": ("rear left", "rear-left", "rl"),
        "RR": ("rear right", "rear-right", "rr"),
    }
    tokens = corner_map.get(corner.upper(), ())
    return any(t in label_lower for t in tokens)


def assert_corner_detected(summary: dict[str, Any], expected_corner: str, msg: str = "") -> None:
    """Assert the top cause points to *expected_corner* (FL/FR/RL/RR)."""
    label = top_corner_label(summary)
    assert label is not None, f"No top cause found. {msg}"
    assert _corner_in_label(label, expected_corner), (
        f"Expected corner {expected_corner} in '{label}'. {msg}"
    )


def _cause_source(cause: dict[str, Any]) -> str:
    """Get the source field from a top-cause dict (handles both field names)."""
    return (cause.get("source") or cause.get("suspected_source") or "").lower()


def assert_no_wheel_fault(summary: dict[str, Any], msg: str = "") -> None:
    """Assert no wheel/tire fault is diagnosed with medium+ confidence.

    Low-confidence matches (< 0.40) are tolerated because broadband noise
    can accidentally align with wheel-order frequencies at certain speeds.
    """
    causes = summary.get("top_causes") or []
    for c in causes:
        src = _cause_source(c)
        conf = float(c.get("confidence", 0))
        if conf >= 0.40 and "wheel" in src:
            loc = c.get("strongest_location") or c.get("location_hotspot", "")
            raise AssertionError(f"Unexpected wheel fault: {src} @ {loc} conf={conf:.2f}. {msg}")


# ---------------------------------------------------------------------------
# Additional assertion helpers
# ---------------------------------------------------------------------------


def assert_wheel_source(summary: dict[str, Any], msg: str = "") -> None:
    """Assert the top cause identifies a wheel/tire source."""
    top = extract_top(summary)
    assert top is not None, f"No top cause found. {msg}"
    src = _cause_source(top)
    assert "wheel" in src or "tire" in src, f"Expected wheel/tire source, got '{src}'. {msg}"


def assert_source_is(summary: dict[str, Any], expected: str, msg: str = "") -> None:
    """Assert the top cause's source contains *expected* (case-insensitive)."""
    top = extract_top(summary)
    assert top is not None, f"No top cause found. {msg}"
    src = _cause_source(top)
    assert expected.lower() in src, f"Expected '{expected}' in source, got '{src}'. {msg}"


def assert_confidence_between(
    summary: dict[str, Any], lo: float, hi: float, msg: str = ""
) -> None:
    """Assert top cause confidence is within [lo, hi]."""
    conf = top_confidence(summary)
    assert lo <= conf <= hi, f"Confidence {conf:.3f} not in [{lo}, {hi}]. {msg}"


def assert_strongest_location(
    summary: dict[str, Any], expected_sensor: str, msg: str = ""
) -> None:
    """Assert the top cause's strongest_location matches *expected_sensor*."""
    top = extract_top(summary)
    assert top is not None, f"No top cause found. {msg}"
    loc = (top.get("strongest_location") or "").lower()
    assert loc == expected_sensor.lower(), (
        f"Expected strongest_location='{expected_sensor}', got '{loc}'. {msg}"
    )
