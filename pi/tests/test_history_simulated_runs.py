"""Simulated-run integration tests for the VibeSensor analysis pipeline.

Each test synthesises realistic sensor data (speed ramps, injected vibration
orders, multi-sensor layouts) and pushes it through the full pipeline:

    HistoryDB  →  create_run  →  append_samples  →  finalize_run
               →  summarize_run_data  →  store_analysis  →  verify findings
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from vibesensor.analysis_settings import (
    tire_circumference_m_from_spec,
    wheel_hz_from_speed_kmh,
)
from vibesensor.history_db import HistoryDB
from vibesensor.report_analysis import summarize_run_data
from vibesensor.runlog import normalize_sample_record

# ---------------------------------------------------------------------------
# Shared tyre / drivetrain constants
# ---------------------------------------------------------------------------
_TIRE_WIDTH_MM = 225.0
_TIRE_ASPECT_PCT = 45.0
_RIM_IN = 18.0
_FINAL_DRIVE = 3.46
_GEAR_RATIO = 0.79
_TIRE_CIRC = tire_circumference_m_from_spec(_TIRE_WIDTH_MM, _TIRE_ASPECT_PCT, _RIM_IN)
assert _TIRE_CIRC is not None  # ≈ 2.09 m


# ---------------------------------------------------------------------------
# Helper: default metadata
# ---------------------------------------------------------------------------
def _make_metadata(**overrides: object) -> dict:
    base: dict[str, object] = {
        "run_id": "sim-run",
        "start_time_utc": "2025-06-01T10:00:00+00:00",
        "record_type": "run_metadata",
        "schema_version": "v2-jsonl",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 800,
        "feature_interval_s": 0.25,
        "fft_window_size_samples": 2048,
        "fft_window_type": "hann",
        "peak_picker_method": "canonical_strength_metrics_module",
        "accel_scale_g_per_lsb": 1.0 / 256.0,
        "tire_width_mm": _TIRE_WIDTH_MM,
        "tire_aspect_pct": _TIRE_ASPECT_PCT,
        "rim_in": _RIM_IN,
        "final_drive_ratio": _FINAL_DRIVE,
        "current_gear_ratio": _GEAR_RATIO,
        "tire_circumference_m": _TIRE_CIRC,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Helper: single sample record
# ---------------------------------------------------------------------------
def _make_sample(
    t_s: float,
    speed_kmh: float,
    client_id: str,
    client_name: str,
    dominant_freq_hz: float,
    vib_amp: float,
    noise_amp: float = 0.002,
    top_peaks: list[dict[str, float]] | None = None,
) -> dict:
    strength_db = 20.0 * math.log10((vib_amp + 1e-9) / (noise_amp + 1e-9))
    if strength_db >= 34:
        bucket = "l5"
    elif strength_db >= 28:
        bucket = "l4"
    elif strength_db >= 22:
        bucket = "l3"
    elif strength_db >= 16:
        bucket = "l2"
    elif strength_db >= 10:
        bucket = "l1"
    else:
        bucket = None  # below reporting threshold

    if top_peaks is None:
        top_peaks = [{"hz": dominant_freq_hz, "amp": vib_amp}]
        # Add small noise peaks at pseudo-random frequencies.
        for i in range(1, 4):
            noise_hz = 30.0 + i * 17.3 + (t_s % 5.0) * 1.1
            top_peaks.append({"hz": noise_hz, "amp": noise_amp * (0.3 + 0.1 * i)})

    return {
        "record_type": "sample",
        "t_s": t_s,
        "speed_kmh": speed_kmh,
        "accel_x_g": vib_amp * 0.7,
        "accel_y_g": vib_amp * 0.5,
        "accel_z_g": vib_amp,
        "vib_mag_rms_g": vib_amp,
        "vib_mag_p2p_g": vib_amp * 2.5,
        "dominant_freq_hz": dominant_freq_hz,
        "noise_floor_amp_p20_g": noise_amp,
        "strength_floor_amp_g": noise_amp,
        "strength_peak_band_rms_amp_g": vib_amp * 1.5,
        "strength_db": strength_db,
        "strength_bucket": bucket,
        "client_id": client_id,
        "client_name": client_name,
        "top_peaks": top_peaks,
    }


# ---------------------------------------------------------------------------
# Helper: compute injected frequency for a given order type + speed
# ---------------------------------------------------------------------------
def _injected_freq(
    order_type: str,
    order_multiplier: float,
    speed_kmh: float,
) -> float:
    whz = wheel_hz_from_speed_kmh(speed_kmh, _TIRE_CIRC)
    assert whz is not None
    if order_type == "wheel":
        return whz * order_multiplier
    if order_type == "driveshaft":
        return whz * _FINAL_DRIVE * order_multiplier
    if order_type == "engine":
        return whz * _FINAL_DRIVE * _GEAR_RATIO * order_multiplier
    raise ValueError(order_type)


# ---------------------------------------------------------------------------
# Helper: interpolate speed from a profile
# ---------------------------------------------------------------------------
def _speed_at(
    t: float,
    profile: list[tuple[float, float, float, float]],
) -> float:
    for start_t, end_t, start_kmh, end_kmh in profile:
        if start_t <= t <= end_t:
            frac = (t - start_t) / max(1e-9, end_t - start_t)
            return start_kmh + (end_kmh - start_kmh) * frac
    return profile[-1][3]  # clamp to last segment end speed


# ---------------------------------------------------------------------------
# Helper: generate a full set of run samples
# ---------------------------------------------------------------------------
def _generate_run_samples(
    *,
    duration_s: float = 20.0,
    sample_hz: int = 4,
    speed_profile: list[tuple[float, float, float, float]],
    sensors: list[dict[str, str]],
    injected_vibration: dict,
) -> list[dict]:
    """Return a list of sample dicts for the simulated run.

    *speed_profile*: list of ``(start_t, end_t, start_kmh, end_kmh)``
    *sensors*: ``[{client_id, client_name, location}, ...]``
    *injected_vibration*: ``{target_sensor_idx, order_type,
        order_multiplier, amp, noise_amp}``
    """
    dt = 1.0 / sample_hz
    n_samples = int(duration_s * sample_hz)
    target_idx = injected_vibration["target_sensor_idx"]
    order_type = injected_vibration["order_type"]
    order_mult = injected_vibration["order_multiplier"]
    vib_amp = injected_vibration["amp"]
    noise_amp = injected_vibration["noise_amp"]

    samples: list[dict] = []
    for i in range(n_samples):
        t = i * dt
        speed = _speed_at(t, speed_profile)
        inj_freq = _injected_freq(order_type, order_mult, speed)

        for s_idx, sensor in enumerate(sensors):
            if s_idx == target_idx:
                sample = _make_sample(
                    t_s=t,
                    speed_kmh=speed,
                    client_id=sensor["client_id"],
                    client_name=sensor["client_name"],
                    dominant_freq_hz=inj_freq,
                    vib_amp=vib_amp,
                    noise_amp=noise_amp,
                )
            else:
                # Non-target sensor: low-level noise only.
                noise_freq = 25.0 + (t % 7.0) * 3.0 + s_idx * 11.0
                sample = _make_sample(
                    t_s=t,
                    speed_kmh=speed,
                    client_id=sensor["client_id"],
                    client_name=sensor["client_name"],
                    dominant_freq_hz=noise_freq,
                    vib_amp=noise_amp * 0.8,
                    noise_amp=noise_amp,
                )
            samples.append(sample)
    return samples


# ---------------------------------------------------------------------------
# Helper: run the full pipeline (DB → analysis → store → retrieve)
# ---------------------------------------------------------------------------
def _run_full_pipeline(
    tmp_path: Path,
    metadata: dict,
    samples: list[dict],
) -> tuple[HistoryDB, str, dict]:
    db_path = tmp_path / "history.db"
    db = HistoryDB(db_path)
    run_id = str(metadata["run_id"])

    db.create_run(run_id, str(metadata["start_time_utc"]), metadata)
    db.append_samples(run_id, samples)
    db.finalize_run(run_id, "2025-06-01T10:30:00+00:00")

    normalised = [normalize_sample_record(s) for s in samples]
    analysis = summarize_run_data(metadata, normalised, lang="en", include_samples=False)
    assert isinstance(analysis, dict), "summarize_run_data must return dict"
    assert "findings" in analysis, "analysis must contain 'findings'"

    db.store_analysis(run_id, analysis)
    stored = db.get_run_analysis(run_id)
    assert stored is not None, "stored analysis should be retrievable"

    return db, run_id, analysis


# ---------------------------------------------------------------------------
# Sensor presets
# ---------------------------------------------------------------------------
_FOUR_WHEEL_SENSORS = [
    {
        "client_id": "sens-fl",
        "client_name": "Front Left Wheel",
        "location": "front_left",
    },
    {
        "client_id": "sens-fr",
        "client_name": "Front Right Wheel",
        "location": "front_right",
    },
    {
        "client_id": "sens-rl",
        "client_name": "Rear Left Wheel",
        "location": "rear_left",
    },
    {
        "client_id": "sens-rr",
        "client_name": "Rear Right Wheel",
        "location": "rear_right",
    },
]


# ===================================================================
# Default tests (no special marker)
# ===================================================================


class TestSimWheel1xFrontLeft:
    """Inject wheel 1x vibration at the Front Left Wheel sensor."""

    def test_sim_wheel_1x_front_left(self, tmp_path: Path) -> None:
        """Wheel 1x order on FL during a 60→100 km/h ramp."""
        meta = _make_metadata(run_id="sim-wheel-1x-fl")
        samples = _generate_run_samples(
            duration_s=20.0,
            sample_hz=4,
            speed_profile=[(0.0, 20.0, 60.0, 100.0)],
            sensors=_FOUR_WHEEL_SENSORS,
            injected_vibration={
                "target_sensor_idx": 0,
                "order_type": "wheel",
                "order_multiplier": 1,
                "amp": 0.05,
                "noise_amp": 0.003,
            },
        )
        _db, _rid, analysis = _run_full_pipeline(tmp_path, meta, samples)
        findings = analysis["findings"]
        wheel_findings = [
            f for f in findings if "wheel" in str(f.get("suspected_source", "")).lower()
        ]
        assert wheel_findings, "expected at least one wheel finding"
        best = max(wheel_findings, key=lambda f: f["confidence_0_to_1"])
        assert best["confidence_0_to_1"] > 0.3, f"confidence too low: {best['confidence_0_to_1']}"
        hotspot = best.get("location_hotspot")
        assert hotspot is not None, "location_hotspot should exist"
        assert "Front Left" in hotspot["location"]


class TestSimWheel2xRearRight:
    """Inject wheel 2x vibration at the Rear Right Wheel sensor."""

    def test_sim_wheel_2x_rear_right(self, tmp_path: Path) -> None:
        """Wheel 2x order on RR during a 50→90 km/h ramp."""
        meta = _make_metadata(run_id="sim-wheel-2x-rr")
        samples = _generate_run_samples(
            duration_s=20.0,
            sample_hz=4,
            speed_profile=[(0.0, 20.0, 50.0, 90.0)],
            sensors=_FOUR_WHEEL_SENSORS,
            injected_vibration={
                "target_sensor_idx": 3,
                "order_type": "wheel",
                "order_multiplier": 2,
                "amp": 0.04,
                "noise_amp": 0.003,
            },
        )
        _db, _rid, analysis = _run_full_pipeline(tmp_path, meta, samples)
        findings = analysis["findings"]
        wheel_findings = [
            f for f in findings if "wheel" in str(f.get("suspected_source", "")).lower()
        ]
        assert wheel_findings, "expected wheel finding"
        hotspot = wheel_findings[0].get("location_hotspot")
        assert hotspot is not None
        assert "Rear Right" in hotspot["location"]


class TestSimEngine2xEngineBay:
    """Inject engine 2x vibration at the Engine Bay sensor."""

    def test_sim_engine_2x_engine_bay(self, tmp_path: Path) -> None:
        """Engine 2x order on Engine Bay during 70→110 km/h ramp."""
        sensors = [
            {
                "client_id": "sens-eb",
                "client_name": "Engine Bay",
                "location": "engine_bay",
            },
            {
                "client_id": "sens-fl",
                "client_name": "Front Left Wheel",
                "location": "front_left",
            },
            {
                "client_id": "sens-rl",
                "client_name": "Rear Left Wheel",
                "location": "rear_left",
            },
        ]
        meta = _make_metadata(run_id="sim-engine-2x")
        samples = _generate_run_samples(
            duration_s=20.0,
            sample_hz=4,
            speed_profile=[(0.0, 20.0, 70.0, 110.0)],
            sensors=sensors,
            injected_vibration={
                "target_sensor_idx": 0,
                "order_type": "engine",
                "order_multiplier": 2,
                "amp": 0.06,
                "noise_amp": 0.003,
            },
        )
        _db, _rid, analysis = _run_full_pipeline(tmp_path, meta, samples)
        findings = analysis["findings"]
        engine_findings = [
            f for f in findings if "engine" in str(f.get("suspected_source", "")).lower()
        ]
        assert engine_findings, "expected engine finding"


class TestSimDriveshaft1xTunnel:
    """Inject driveshaft 1x vibration at the Driveshaft Tunnel sensor."""

    def test_sim_driveshaft_1x_tunnel(self, tmp_path: Path) -> None:
        """Driveshaft 1x at Tunnel sensor during 55→95 km/h ramp."""
        sensors = [
            {
                "client_id": "sens-ds",
                "client_name": "Driveshaft Tunnel",
                "location": "tunnel",
            },
            {
                "client_id": "sens-fr",
                "client_name": "Front Right Wheel",
                "location": "front_right",
            },
            {
                "client_id": "sens-rr",
                "client_name": "Rear Right Wheel",
                "location": "rear_right",
            },
        ]
        meta = _make_metadata(run_id="sim-ds-1x")
        samples = _generate_run_samples(
            duration_s=20.0,
            sample_hz=4,
            speed_profile=[(0.0, 20.0, 55.0, 95.0)],
            sensors=sensors,
            injected_vibration={
                "target_sensor_idx": 0,
                "order_type": "driveshaft",
                "order_multiplier": 1,
                "amp": 0.05,
                "noise_amp": 0.003,
            },
        )
        _db, _rid, analysis = _run_full_pipeline(tmp_path, meta, samples)
        findings = analysis["findings"]
        ds_findings = [
            f for f in findings if "driveline" in str(f.get("suspected_source", "")).lower()
        ]
        assert ds_findings, "expected driveline finding"


class TestSimWeakWheel1xMasked:
    """Weak wheel 1x vibration with elevated noise floor."""

    def test_sim_weak_wheel_1x_masked(self, tmp_path: Path) -> None:
        """Weak wheel 1x on FR with high noise — may or may not detect."""
        meta = _make_metadata(run_id="sim-weak-1x")
        samples = _generate_run_samples(
            duration_s=20.0,
            sample_hz=4,
            speed_profile=[(0.0, 20.0, 60.0, 100.0)],
            sensors=_FOUR_WHEEL_SENSORS,
            injected_vibration={
                "target_sensor_idx": 1,
                "order_type": "wheel",
                "order_multiplier": 1,
                "amp": 0.015,
                "noise_amp": 0.005,
            },
        )
        _db, _rid, analysis = _run_full_pipeline(tmp_path, meta, samples)
        findings = analysis["findings"]
        wheel_findings = [
            f for f in findings if "wheel" in str(f.get("suspected_source", "")).lower()
        ]
        if wheel_findings:
            hotspot = wheel_findings[0].get("location_hotspot")
            if hotspot is not None:
                assert "Front Right" in hotspot["location"], (
                    "if detected, Front Right should rank highest"
                )


# ===================================================================
# Long-simulation tests
# ===================================================================


@pytest.mark.long_sim
class TestSimLongMultiSpeedSweep:
    """60 s run with three speed segments."""

    def test_sim_long_multi_speed_sweep(self, tmp_path: Path) -> None:
        """Three-segment speed sweep detecting wheel 1x on FL."""
        meta = _make_metadata(run_id="sim-long-sweep")
        samples = _generate_run_samples(
            duration_s=60.0,
            sample_hz=4,
            speed_profile=[
                (0.0, 20.0, 50.0, 80.0),
                (20.0, 40.0, 80.0, 100.0),
                (40.0, 60.0, 100.0, 70.0),
            ],
            sensors=_FOUR_WHEEL_SENSORS,
            injected_vibration={
                "target_sensor_idx": 0,
                "order_type": "wheel",
                "order_multiplier": 1,
                "amp": 0.05,
                "noise_amp": 0.003,
            },
        )
        _db, _rid, analysis = _run_full_pipeline(tmp_path, meta, samples)
        wheel_findings = [
            f for f in analysis["findings"] if "wheel" in str(f.get("suspected_source", "")).lower()
        ]
        assert wheel_findings, "expected wheel finding in multi-sweep"


@pytest.mark.long_sim
class TestSimLongEngine1xWithNoise:
    """45 s run detecting engine 1x amidst noise."""

    def test_sim_long_engine_1x_with_noise(self, tmp_path: Path) -> None:
        """Engine 1x on Engine Bay over 45 s ramp."""
        sensors = [
            {
                "client_id": "sens-eb",
                "client_name": "Engine Bay",
                "location": "engine_bay",
            },
            {
                "client_id": "sens-fl",
                "client_name": "Front Left Wheel",
                "location": "front_left",
            },
            {
                "client_id": "sens-rr",
                "client_name": "Rear Right Wheel",
                "location": "rear_right",
            },
        ]
        meta = _make_metadata(run_id="sim-long-engine-1x")
        samples = _generate_run_samples(
            duration_s=45.0,
            sample_hz=4,
            speed_profile=[(0.0, 45.0, 60.0, 120.0)],
            sensors=sensors,
            injected_vibration={
                "target_sensor_idx": 0,
                "order_type": "engine",
                "order_multiplier": 1,
                "amp": 0.05,
                "noise_amp": 0.004,
            },
        )
        _db, _rid, analysis = _run_full_pipeline(tmp_path, meta, samples)
        engine_findings = [
            f
            for f in analysis["findings"]
            if "engine" in str(f.get("suspected_source", "")).lower()
        ]
        assert engine_findings, "expected engine finding"


@pytest.mark.long_sim
class TestSimLongWheel1xAllCorners:
    """30 s run — test each wheel corner individually."""

    @pytest.mark.parametrize(
        "corner_idx, corner_label",
        [
            (0, "Front Left"),
            (1, "Front Right"),
            (2, "Rear Left"),
            (3, "Rear Right"),
        ],
    )
    def test_sim_long_wheel_1x_all_corners(
        self,
        tmp_path: Path,
        corner_idx: int,
        corner_label: str,
    ) -> None:
        """Wheel 1x injected at *corner_label* over a 30 s ramp."""
        meta = _make_metadata(run_id=f"sim-corner-{corner_idx}")
        samples = _generate_run_samples(
            duration_s=30.0,
            sample_hz=4,
            speed_profile=[(0.0, 30.0, 55.0, 105.0)],
            sensors=_FOUR_WHEEL_SENSORS,
            injected_vibration={
                "target_sensor_idx": corner_idx,
                "order_type": "wheel",
                "order_multiplier": 1,
                "amp": 0.05,
                "noise_amp": 0.003,
            },
        )
        _db, _rid, analysis = _run_full_pipeline(tmp_path, meta, samples)
        wheel_findings = [
            f for f in analysis["findings"] if "wheel" in str(f.get("suspected_source", "")).lower()
        ]
        assert wheel_findings, f"expected wheel finding at {corner_label}"
        hotspot = wheel_findings[0].get("location_hotspot")
        assert hotspot is not None
        assert corner_label in hotspot["location"]


@pytest.mark.long_sim
class TestSimLongHighSpeed:
    """20 s run at high speed (100→160 km/h)."""

    def test_sim_long_high_speed(self, tmp_path: Path) -> None:
        """Wheel 1x on RL at highway speeds."""
        meta = _make_metadata(run_id="sim-high-speed")
        samples = _generate_run_samples(
            duration_s=20.0,
            sample_hz=4,
            speed_profile=[(0.0, 20.0, 100.0, 160.0)],
            sensors=_FOUR_WHEEL_SENSORS,
            injected_vibration={
                "target_sensor_idx": 2,
                "order_type": "wheel",
                "order_multiplier": 1,
                "amp": 0.05,
                "noise_amp": 0.003,
            },
        )
        _db, _rid, analysis = _run_full_pipeline(tmp_path, meta, samples)
        wheel_findings = [
            f for f in analysis["findings"] if "wheel" in str(f.get("suspected_source", "")).lower()
        ]
        assert wheel_findings, "expected wheel finding at high speed"
        hotspot = wheel_findings[0].get("location_hotspot")
        assert hotspot is not None
        assert "Rear Left" in hotspot["location"]


@pytest.mark.long_sim
class TestSimLongLowSpeed:
    """20 s run at low speed (30→60 km/h)."""

    def test_sim_long_low_speed(self, tmp_path: Path) -> None:
        """Driveshaft 1x on Tunnel sensor at low urban speeds."""
        sensors = [
            {
                "client_id": "sens-ds",
                "client_name": "Driveshaft Tunnel",
                "location": "tunnel",
            },
            {
                "client_id": "sens-fl",
                "client_name": "Front Left Wheel",
                "location": "front_left",
            },
            {
                "client_id": "sens-rr",
                "client_name": "Rear Right Wheel",
                "location": "rear_right",
            },
        ]
        meta = _make_metadata(run_id="sim-low-speed")
        samples = _generate_run_samples(
            duration_s=20.0,
            sample_hz=4,
            speed_profile=[(0.0, 20.0, 30.0, 60.0)],
            sensors=sensors,
            injected_vibration={
                "target_sensor_idx": 0,
                "order_type": "driveshaft",
                "order_multiplier": 1,
                "amp": 0.05,
                "noise_amp": 0.003,
            },
        )
        _db, _rid, analysis = _run_full_pipeline(tmp_path, meta, samples)
        ds_findings = [
            f
            for f in analysis["findings"]
            if "driveline" in str(f.get("suspected_source", "")).lower()
        ]
        assert ds_findings, "expected driveline finding at low speed"
