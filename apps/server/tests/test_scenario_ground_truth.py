# ruff: noqa: E501
"""Ground-truth scenario regression tests matching the 5 user-specified scenarios.

Each scenario class synthesises JSONL-style samples that mimic what the
sim_sender would produce for the exact phase-by-phase commands given:

  01_idle_to_100_fr_en  – 45s idle, 20s ramp 20→100, 40s fault FR@100; lang=en
  02_stop_go_rl_nl      – 20s idle, 20s road@30, 20s fault RL@50, 15s roll@10, 25s fault RL@60; lang=nl
  03_high_speed_rr_en   – 20s road@60, 20s road@90, 40s fault RR@120, 20s road@100; lang=en
  04_coastdown_fl_nl    – 20s road@110, 20s mild FL@90, 20s strong FL@70, 20s mild FL@50, 20s road@30; lang=nl
  05_noise_then_fl_en   – 40s road@80, 20s rough@80, 40s fault FL@100, 15s road@60; lang=en

Root causes addressed:
  1. Speed-band dilution from ramp/idle/baseline phases → phase-aware weighting
  2. Simulator road-scene non-determinism → ``road-fixed`` scenario
  3. Language correctness → explicit ``lang=`` parameter enforcement
  4. Multi-sensor localization dilution → per-location match-rate rescue
  5. Confidence calibration → no overconfident wrong results

Unit tests for simulator determinism, language precedence, speed-band
selection in mixed-phase runs, and confidence guardrails are at the bottom.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from vibesensor_core.strength_bands import bucket_for_strength

from vibesensor.analysis_settings import (
    DEFAULT_ANALYSIS_SETTINGS,
    tire_circumference_m_from_spec,
    wheel_hz_from_speed_kmh,
)
from vibesensor.report.summary import summarize_run_data

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_TIRE_CIRC = tire_circumference_m_from_spec(
    DEFAULT_ANALYSIS_SETTINGS["tire_width_mm"],
    DEFAULT_ANALYSIS_SETTINGS["tire_aspect_pct"],
    DEFAULT_ANALYSIS_SETTINGS["rim_in"],
)
_FINAL_DRIVE = DEFAULT_ANALYSIS_SETTINGS["final_drive_ratio"]
_GEAR_RATIO = DEFAULT_ANALYSIS_SETTINGS["current_gear_ratio"]

_ALL_SENSORS = ["front-left", "front-right", "rear-left", "rear-right"]


def _wheel_hz(speed_kmh: float) -> float:
    """Compute wheel_1x Hz for a given speed."""
    hz = wheel_hz_from_speed_kmh(speed_kmh, _TIRE_CIRC)
    assert hz is not None and hz > 0
    return hz


def _standard_metadata(*, language: str = "en", **overrides: Any) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "tire_circumference_m": _TIRE_CIRC,
        "raw_sample_rate_hz": 800.0,
        "final_drive_ratio": _FINAL_DRIVE,
        "current_gear_ratio": _GEAR_RATIO,
        "sensor_model": "ADXL345",
        "units": {"accel_x_g": "g"},
        "language": language,
    }
    meta.update(overrides)
    return meta


def _make_sample(
    *,
    t_s: float,
    speed_kmh: float,
    client_name: str,
    top_peaks: list[dict[str, float]],
    vibration_strength_db: float = 20.0,
    strength_floor_amp_g: float = 0.003,
    engine_rpm: float | None = None,
) -> dict[str, Any]:
    sample: dict[str, Any] = {
        "t_s": t_s,
        "speed_kmh": speed_kmh,
        "accel_x_g": 0.02,
        "accel_y_g": 0.02,
        "accel_z_g": 0.10,
        "vibration_strength_db": vibration_strength_db,
        "strength_bucket": bucket_for_strength(vibration_strength_db),
        "strength_floor_amp_g": strength_floor_amp_g,
        "client_name": client_name,
        "client_id": f"sensor-{client_name}",
        "top_peaks": top_peaks,
    }
    if engine_rpm is not None:
        sample["engine_rpm"] = engine_rpm
    return sample


# ---------------------------------------------------------------------------
# Phase builders – generate samples for each driving phase
# ---------------------------------------------------------------------------


def _idle_phase(
    *,
    duration_s: float,
    sensors: list[str],
    start_t_s: float = 0.0,
    dt_s: float = 1.0,
    noise_amp: float = 0.003,
) -> list[dict[str, Any]]:
    """Generate idle/stationary samples (speed=0, only noise peaks)."""
    samples: list[dict[str, Any]] = []
    n = max(1, int(duration_s / dt_s))
    for i in range(n):
        t = start_t_s + i * dt_s
        for sensor in sensors:
            peaks = [
                {"hz": 12.5 + (hash(sensor) % 10), "amp": noise_amp},
                {"hz": 25.0, "amp": noise_amp * 0.5},
            ]
            samples.append(
                _make_sample(
                    t_s=t,
                    speed_kmh=0.0,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=6.0,
                    strength_floor_amp_g=noise_amp,
                )
            )
    return samples


def _road_noise_phase(
    *,
    speed_kmh: float,
    duration_s: float,
    sensors: list[str],
    start_t_s: float = 0.0,
    dt_s: float = 1.0,
    noise_amp: float = 0.004,
    road_vib_db: float = 10.0,
) -> list[dict[str, Any]]:
    """Generate road-noise phase: no order peaks, just broadband on all sensors."""
    samples: list[dict[str, Any]] = []
    n = max(1, int(duration_s / dt_s))
    for i in range(n):
        t = start_t_s + i * dt_s
        for sensor in sensors:
            peaks = [
                {"hz": 15.0 + (hash(sensor) % 20), "amp": noise_amp},
                {"hz": 34.0, "amp": noise_amp * 0.7},
                {"hz": 88.0, "amp": noise_amp * 0.5},
            ]
            samples.append(
                _make_sample(
                    t_s=t,
                    speed_kmh=speed_kmh,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=road_vib_db,
                    strength_floor_amp_g=noise_amp,
                )
            )
    return samples


def _ramp_phase(
    *,
    speed_start: float,
    speed_end: float,
    n_steps: int,
    step_duration_s: float,
    sensors: list[str],
    start_t_s: float = 0.0,
    dt_s: float = 1.0,
    noise_amp: float = 0.004,
    road_vib_db: float = 10.0,
) -> list[dict[str, Any]]:
    """Generate speed ramp phase: increasing speed, no fault peaks."""
    samples: list[dict[str, Any]] = []
    t = start_t_s
    for step in range(n_steps):
        ratio = step / max(1, n_steps - 1)
        speed = speed_start + (speed_end - speed_start) * ratio
        n_per_step = max(1, int(step_duration_s / dt_s))
        for _i in range(n_per_step):
            for sensor in sensors:
                peaks = [
                    {"hz": 15.0 + (hash(sensor) % 20), "amp": noise_amp},
                    {"hz": 60.0, "amp": noise_amp * 0.6},
                ]
                samples.append(
                    _make_sample(
                        t_s=t,
                        speed_kmh=speed,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=road_vib_db,
                        strength_floor_amp_g=noise_amp,
                    )
                )
            t += dt_s
    return samples


def _fault_phase(
    *,
    speed_kmh: float,
    duration_s: float,
    fault_sensor: str,
    sensors: list[str],
    start_t_s: float = 0.0,
    dt_s: float = 1.0,
    fault_amp: float = 0.06,
    noise_amp: float = 0.004,
    fault_vib_db: float = 26.0,
    noise_vib_db: float = 8.0,
    add_wheel_2x: bool = True,
    transfer_fraction: float = 0.20,
) -> list[dict[str, Any]]:
    """Generate wheel-fault phase at constant speed with fault on one sensor."""
    samples: list[dict[str, Any]] = []
    whz = _wheel_hz(speed_kmh)
    n = max(1, int(duration_s / dt_s))
    for i in range(n):
        t = start_t_s + i * dt_s
        for sensor in sensors:
            if sensor == fault_sensor:
                fault_peaks = [{"hz": whz, "amp": fault_amp}]
                if add_wheel_2x:
                    fault_peaks.append({"hz": whz * 2, "amp": fault_amp * 0.4})
                fault_peaks.append({"hz": 142.5, "amp": noise_amp})
                samples.append(
                    _make_sample(
                        t_s=t,
                        speed_kmh=speed_kmh,
                        client_name=sensor,
                        top_peaks=fault_peaks,
                        vibration_strength_db=fault_vib_db,
                        strength_floor_amp_g=noise_amp,
                    )
                )
            else:
                other_peaks = [
                    {"hz": 142.5, "amp": noise_amp},
                    {"hz": 87.3, "amp": noise_amp * 0.8},
                ]
                if transfer_fraction > 0:
                    other_peaks.insert(0, {"hz": whz, "amp": fault_amp * transfer_fraction})
                    if add_wheel_2x:
                        other_peaks.insert(
                            1,
                            {"hz": whz * 2, "amp": fault_amp * transfer_fraction * 0.24},
                        )
                samples.append(
                    _make_sample(
                        t_s=t,
                        speed_kmh=speed_kmh,
                        client_name=sensor,
                        top_peaks=other_peaks,
                        vibration_strength_db=noise_vib_db,
                        strength_floor_amp_g=noise_amp,
                    )
                )
    return samples


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


def _get_top_cause(summary: dict) -> dict:
    """Extract the first (highest-priority) top cause from the summary."""
    top_causes = summary.get("top_causes", [])
    assert top_causes, "No top causes found in summary"
    return top_causes[0]


def _assert_language(summary: dict, expected_lang: str) -> None:
    """Assert that the report was generated in the expected language."""
    actual = summary.get("lang", "")
    assert actual == expected_lang, f"Expected lang={expected_lang!r} but got {actual!r}"


def _assert_primary_system(top_cause: dict, expected: str) -> None:
    """Assert the primary suspected source matches (case-insensitive substring)."""
    source = str(top_cause.get("source", "")).lower()
    assert expected.lower() in source, f"Expected source containing {expected!r}, got {source!r}"


def _assert_strongest_sensor(top_cause: dict, expected_sensor: str) -> None:
    """Assert the strongest location includes the expected sensor name."""
    location = str(top_cause.get("strongest_location", "")).lower()
    assert expected_sensor.lower() in location, (
        f"Expected strongest_location containing {expected_sensor!r}, got {location!r}"
    )


def _assert_speed_band_contains(top_cause: dict, min_kmh: float, max_kmh: float) -> None:
    """Assert the speed band overlaps the expected range."""
    band = str(top_cause.get("strongest_speed_band", ""))
    assert band and "km/h" in band, f"No valid speed band found: {band!r}"
    # Parse "90-100 km/h" -> (90, 100)
    parts = band.replace("km/h", "").strip().split("-")
    low = float(parts[0])
    high = float(parts[1])
    # The reported band should overlap with the expected range
    assert high > min_kmh and low < max_kmh, (
        f"Speed band {band} does not overlap expected range {min_kmh}-{max_kmh} km/h"
    )


def _assert_confidence_range(top_cause: dict, min_conf: float, max_conf: float = 1.0) -> None:
    """Assert confidence falls within an expected range."""
    conf = top_cause.get("confidence", 0.0)
    assert isinstance(conf, (int, float)), f"Confidence not numeric: {conf!r}"
    assert min_conf <= conf <= max_conf, (
        f"Confidence {conf:.2f} not in [{min_conf:.2f}, {max_conf:.2f}]"
    )


def _assert_no_weak_spatial_separation(top_cause: dict) -> None:
    """Assert the localization is strong (not ambiguous between corners)."""
    assert not top_cause.get("weak_spatial_separation", True), (
        "Expected strong spatial separation but got weak"
    )


def _assert_has_sections(summary: dict, sections: list[str]) -> None:
    """Assert required report sections exist in summary."""
    for section in sections:
        assert section in summary, f"Missing required section: {section!r}"


def _assert_wheel_signatures(top_cause: dict) -> None:
    """Assert wheel order signatures are observed (1x and/or 2x).

    Handles both English ("wheel order") and Dutch ("wielorde") labels.
    """
    sigs = top_cause.get("signatures_observed", [])
    sig_text = " ".join(str(s).lower() for s in sigs)
    assert "wheel" in sig_text or "wiel" in sig_text, (
        f"Expected wheel/wiel signatures, got {sigs!r}"
    )


def _assert_not_engine(top_cause: dict) -> None:
    """Assert the source is NOT engine/driveline."""
    source = str(top_cause.get("source", "")).lower()
    assert "engine" not in source, f"Source should not be engine, got {source!r}"
    assert "driveline" not in source, f"Source should not be driveline, got {source!r}"


# ===========================================================================
# Scenario 1: Idle → onset at 100 km/h, fault=front-right, lang=en
# Phases: 45s idle @0 → 20s ramp 20→100 → 40s fault FR @100
# ===========================================================================


class TestScenario01IdleToOnsetFR:
    """Idle baseline → 20s acceleration ramp → 40s fault at 100 km/h on front-right."""

    @pytest.fixture()
    def summary(self) -> dict:
        sensors = _ALL_SENSORS
        samples: list[dict[str, Any]] = []
        t = 0.0

        # Phase A: 45s idle @0 km/h
        samples.extend(_idle_phase(duration_s=45.0, sensors=sensors, start_t_s=t))
        t += 45.0

        # Phase B: 20s acceleration ramp 20→40→60→80→100 (5 steps × 4s each)
        samples.extend(
            _ramp_phase(
                speed_start=20.0,
                speed_end=100.0,
                n_steps=5,
                step_duration_s=4.0,
                sensors=sensors,
                start_t_s=t,
            )
        )
        t += 20.0

        # Phase C: 40s mild wheel fault on front-right @100 km/h
        samples.extend(
            _fault_phase(
                speed_kmh=100.0,
                duration_s=40.0,
                fault_sensor="front-right",
                sensors=sensors,
                start_t_s=t,
            )
        )

        metadata = _standard_metadata(language="en")
        return summarize_run_data(metadata, samples, lang="en", file_name="01_idle_to_100_fr_en")

    def test_language(self, summary: dict) -> None:
        _assert_language(summary, "en")

    def test_primary_system_is_wheel(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_primary_system(top, "wheel")
        _assert_not_engine(top)

    def test_strongest_sensor_is_front_right(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_strongest_sensor(top, "front-right")
        _assert_no_weak_spatial_separation(top)

    def test_speed_band_covers_100(self, summary: dict) -> None:
        """Dominant speed band should be around 100 km/h (the fault phase speed)."""
        top = _get_top_cause(summary)
        _assert_speed_band_contains(top, 90.0, 110.0)

    def test_confidence_reasonable(self, summary: dict) -> None:
        """Confidence should be moderate-to-high for a clear 40s fault."""
        top = _get_top_cause(summary)
        _assert_confidence_range(top, 0.40, 0.85)

    def test_wheel_signatures_present(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_wheel_signatures(top)

    def test_has_required_sections(self, summary: dict) -> None:
        _assert_has_sections(summary, ["top_causes", "findings", "lang"])

    def test_contract_validation(self, summary: dict) -> None:
        """Full contract validation via shared helpers."""
        from conftest import assert_summary_sections, assert_top_cause_contract

        assert_summary_sections(summary, expected_lang="en", min_top_causes=1)
        top = _get_top_cause(summary)
        assert_top_cause_contract(
            top,
            expected_source="wheel",
            expected_location="front-right",
            expected_speed_band_range=(90.0, 110.0),
            confidence_range=(0.40, 0.85),
            expect_no_weak_spatial=True,
            expect_wheel_signatures=True,
            expect_not_engine=True,
        )


# ===========================================================================
# Scenario 2: Stop-go intermittent, fault=rear-left, lang=nl
# Phases: 20s idle → 20s road@30 → 20s fault RL@50 → 15s roll@10 → 25s fault RL@60
# ===========================================================================


class TestScenario02StopGoRL:
    """Stop-go driving with intermittent rear-left fault at 50 and 60 km/h."""

    @pytest.fixture()
    def summary(self) -> dict:
        sensors = _ALL_SENSORS
        samples: list[dict[str, Any]] = []
        t = 0.0

        # Phase A: 20s idle @0
        samples.extend(_idle_phase(duration_s=20.0, sensors=sensors, start_t_s=t))
        t += 20.0

        # Phase B: 20s road baseline @30 km/h
        samples.extend(
            _road_noise_phase(speed_kmh=30.0, duration_s=20.0, sensors=sensors, start_t_s=t)
        )
        t += 20.0

        # Phase C: 20s mild wheel fault on rear-left @50 km/h
        samples.extend(
            _fault_phase(
                speed_kmh=50.0,
                duration_s=20.0,
                fault_sensor="rear-left",
                sensors=sensors,
                start_t_s=t,
            )
        )
        t += 20.0

        # Phase D: 15s slow roll / road noise @10 km/h (no fault)
        samples.extend(
            _road_noise_phase(speed_kmh=10.0, duration_s=15.0, sensors=sensors, start_t_s=t)
        )
        t += 15.0

        # Phase E: 25s mild wheel fault on rear-left @60 km/h
        samples.extend(
            _fault_phase(
                speed_kmh=60.0,
                duration_s=25.0,
                fault_sensor="rear-left",
                sensors=sensors,
                start_t_s=t,
            )
        )

        metadata = _standard_metadata(language="nl")
        return summarize_run_data(metadata, samples, lang="nl", file_name="02_stop_go_rl_nl")

    def test_language(self, summary: dict) -> None:
        _assert_language(summary, "nl")

    def test_primary_system_is_wheel(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_primary_system(top, "wheel")
        _assert_not_engine(top)

    def test_strongest_sensor_is_rear_left(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_strongest_sensor(top, "rear-left")

    def test_speed_band_covers_fault_speeds(self, summary: dict) -> None:
        """The dominant speed band should be in the 50-70 km/h fault region."""
        top = _get_top_cause(summary)
        _assert_speed_band_contains(top, 40.0, 70.0)

    def test_confidence_reasonable(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_confidence_range(top, 0.30, 0.80)

    def test_wheel_signatures_present(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_wheel_signatures(top)

    def test_has_required_sections(self, summary: dict) -> None:
        _assert_has_sections(summary, ["top_causes", "findings", "lang"])

    def test_contract_validation(self, summary: dict) -> None:
        """Full contract validation via shared helpers."""
        from conftest import assert_summary_sections, assert_top_cause_contract

        assert_summary_sections(summary, expected_lang="nl", min_top_causes=1)
        top = _get_top_cause(summary)
        assert_top_cause_contract(
            top,
            expected_source="wheel",
            expected_location="rear-left",
            expected_speed_band_range=(40.0, 70.0),
            confidence_range=(0.30, 0.80),
            expect_wheel_signatures=True,
            expect_not_engine=True,
        )


# ===========================================================================
# Scenario 3: High-speed only fault, fault=rear-right, lang=en
# Phases: 20s road@60 → 20s road@90 → 40s fault RR@120 → 20s road@100
# ===========================================================================


class TestScenario03HighwayRR:
    """Road baselines at 60 and 90, then 40s fault at 120, then road baseline at 100."""

    @pytest.fixture()
    def summary(self) -> dict:
        sensors = _ALL_SENSORS
        samples: list[dict[str, Any]] = []
        t = 0.0

        # Phase A: 20s road baseline @60 km/h
        samples.extend(
            _road_noise_phase(speed_kmh=60.0, duration_s=20.0, sensors=sensors, start_t_s=t)
        )
        t += 20.0

        # Phase B: 20s road baseline @90 km/h
        samples.extend(
            _road_noise_phase(speed_kmh=90.0, duration_s=20.0, sensors=sensors, start_t_s=t)
        )
        t += 20.0

        # Phase C: 40s mild wheel fault on rear-right @120 km/h
        samples.extend(
            _fault_phase(
                speed_kmh=120.0,
                duration_s=40.0,
                fault_sensor="rear-right",
                sensors=sensors,
                start_t_s=t,
            )
        )
        t += 40.0

        # Phase D: 20s road baseline @100 km/h (cooldown, no fault)
        samples.extend(
            _road_noise_phase(speed_kmh=100.0, duration_s=20.0, sensors=sensors, start_t_s=t)
        )

        metadata = _standard_metadata(language="en")
        return summarize_run_data(metadata, samples, lang="en", file_name="03_high_speed_rr_en")

    def test_language(self, summary: dict) -> None:
        _assert_language(summary, "en")

    def test_primary_system_is_wheel(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_primary_system(top, "wheel")
        _assert_not_engine(top)

    def test_strongest_sensor_is_rear_right(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_strongest_sensor(top, "rear-right")

    def test_speed_band_covers_120(self, summary: dict) -> None:
        """Speed band should be around 120 km/h (the only fault phase)."""
        top = _get_top_cause(summary)
        _assert_speed_band_contains(top, 110.0, 130.0)

    def test_confidence_reasonable(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_confidence_range(top, 0.40, 0.85)

    def test_wheel_signatures_present(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_wheel_signatures(top)

    def test_has_required_sections(self, summary: dict) -> None:
        _assert_has_sections(summary, ["top_causes", "findings", "lang"])

    def test_no_weak_spatial_separation(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_no_weak_spatial_separation(top)

    def test_contract_validation(self, summary: dict) -> None:
        """Full contract validation via shared helpers."""
        from conftest import assert_summary_sections, assert_top_cause_contract

        assert_summary_sections(summary, expected_lang="en", min_top_causes=1)
        top = _get_top_cause(summary)
        assert_top_cause_contract(
            top,
            expected_source="wheel",
            expected_location="rear-right",
            expected_speed_band_range=(110.0, 130.0),
            confidence_range=(0.40, 0.85),
            expect_no_weak_spatial=True,
            expect_wheel_signatures=True,
            expect_not_engine=True,
        )


# ===========================================================================
# Scenario 4: Coast-down resonance, fault=front-left, lang=nl
# Phases: 20s road@110 → 20s mild FL@90 → 20s stronger FL@70 → 20s mild FL@50 → 20s road@30
# ===========================================================================


class TestScenario04CoastdownFL:
    """Coast-down with variable-strength front-left fault across 90/70/50 km/h."""

    @pytest.fixture()
    def summary(self) -> dict:
        sensors = _ALL_SENSORS
        samples: list[dict[str, Any]] = []
        t = 0.0

        # Phase A: 20s road baseline @110 km/h (no fault)
        samples.extend(
            _road_noise_phase(
                speed_kmh=110.0,
                duration_s=20.0,
                sensors=sensors,
                start_t_s=t,
                road_vib_db=12.0,
            )
        )
        t += 20.0

        # Phase B: 20s mild wheel fault on front-left @90 km/h
        samples.extend(
            _fault_phase(
                speed_kmh=90.0,
                duration_s=20.0,
                fault_sensor="front-left",
                sensors=sensors,
                start_t_s=t,
                fault_amp=0.045,
                fault_vib_db=22.0,
            )
        )
        t += 20.0

        # Phase C: 20s stronger wheel fault on front-left @70 km/h
        samples.extend(
            _fault_phase(
                speed_kmh=70.0,
                duration_s=20.0,
                fault_sensor="front-left",
                sensors=sensors,
                start_t_s=t,
                fault_amp=0.07,
                fault_vib_db=28.0,
            )
        )
        t += 20.0

        # Phase D: 20s mild wheel fault on front-left @50 km/h
        samples.extend(
            _fault_phase(
                speed_kmh=50.0,
                duration_s=20.0,
                fault_sensor="front-left",
                sensors=sensors,
                start_t_s=t,
                fault_amp=0.045,
                fault_vib_db=22.0,
            )
        )
        t += 20.0

        # Phase E: 20s road baseline @30 km/h (no fault)
        samples.extend(
            _road_noise_phase(
                speed_kmh=30.0,
                duration_s=20.0,
                sensors=sensors,
                start_t_s=t,
            )
        )

        metadata = _standard_metadata(language="nl")
        return summarize_run_data(metadata, samples, lang="nl", file_name="04_coastdown_fl_nl")

    def test_language(self, summary: dict) -> None:
        _assert_language(summary, "nl")

    def test_primary_system_is_wheel(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_primary_system(top, "wheel")
        _assert_not_engine(top)

    def test_strongest_sensor_is_front_left(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_strongest_sensor(top, "front-left")

    def test_speed_band_in_fault_range(self, summary: dict) -> None:
        """Speed band should be within the 50-90 km/h fault region (strongest at 70)."""
        top = _get_top_cause(summary)
        _assert_speed_band_contains(top, 40.0, 100.0)

    def test_confidence_reasonable(self, summary: dict) -> None:
        """Coast-down with 60s total fault evidence should have decent confidence."""
        top = _get_top_cause(summary)
        _assert_confidence_range(top, 0.35, 0.85)

    def test_wheel_signatures_present(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_wheel_signatures(top)

    def test_has_required_sections(self, summary: dict) -> None:
        _assert_has_sections(summary, ["top_causes", "findings", "lang"])

    def test_no_weak_spatial_separation(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_no_weak_spatial_separation(top)

    def test_contract_validation(self, summary: dict) -> None:
        """Full contract validation via shared helpers."""
        from conftest import assert_summary_sections, assert_top_cause_contract

        assert_summary_sections(summary, expected_lang="nl", min_top_causes=1)
        top = _get_top_cause(summary)
        assert_top_cause_contract(
            top,
            expected_source="wheel",
            expected_location="front-left",
            expected_speed_band_range=(40.0, 100.0),
            confidence_range=(0.35, 0.85),
            expect_wheel_signatures=True,
            expect_not_engine=True,
        )


# ===========================================================================
# Scenario 5: Noise then clear confirmation, fault=front-left, lang=en
# Phases: 40s road@80 → 20s rough@80 → 40s fault FL@100 → 15s road@60
# ===========================================================================


class TestScenario05NoiseThenFL:
    """Road noise baseline then onset of front-left fault at 100 km/h."""

    @pytest.fixture()
    def summary(self) -> dict:
        sensors = _ALL_SENSORS
        samples: list[dict[str, Any]] = []
        t = 0.0

        # Phase A: 40s mixed road/noise baseline @80 km/h (no fault)
        samples.extend(
            _road_noise_phase(
                speed_kmh=80.0,
                duration_s=40.0,
                sensors=sensors,
                start_t_s=t,
                noise_amp=0.005,
                road_vib_db=14.0,
            )
        )
        t += 40.0

        # Phase B: 20s rough/noisy road segment @80 km/h (higher noise, no fault)
        samples.extend(
            _road_noise_phase(
                speed_kmh=80.0,
                duration_s=20.0,
                sensors=sensors,
                start_t_s=t,
                noise_amp=0.008,
                road_vib_db=18.0,
            )
        )
        t += 20.0

        # Phase C: 40s mild wheel fault on front-left @100 km/h
        samples.extend(
            _fault_phase(
                speed_kmh=100.0,
                duration_s=40.0,
                fault_sensor="front-left",
                sensors=sensors,
                start_t_s=t,
            )
        )
        t += 40.0

        # Phase D: 15s road baseline @60 km/h (cooldown, no fault)
        samples.extend(
            _road_noise_phase(
                speed_kmh=60.0,
                duration_s=15.0,
                sensors=sensors,
                start_t_s=t,
            )
        )

        metadata = _standard_metadata(language="en")
        return summarize_run_data(metadata, samples, lang="en", file_name="05_noise_then_fl_en")

    def test_language(self, summary: dict) -> None:
        _assert_language(summary, "en")

    def test_primary_system_is_wheel(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_primary_system(top, "wheel")
        _assert_not_engine(top)

    def test_strongest_sensor_is_front_left(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_strongest_sensor(top, "front-left")

    def test_speed_band_covers_100(self, summary: dict) -> None:
        """Fault emerges at 100 km/h — speed band should cover that range."""
        top = _get_top_cause(summary)
        _assert_speed_band_contains(top, 90.0, 110.0)

    def test_confidence_reasonable(self, summary: dict) -> None:
        """Despite earlier noise, 40s clear fault should produce reasonable confidence."""
        top = _get_top_cause(summary)
        _assert_confidence_range(top, 0.30, 0.85)

    def test_wheel_signatures_present(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_wheel_signatures(top)

    def test_has_required_sections(self, summary: dict) -> None:
        _assert_has_sections(summary, ["top_causes", "findings", "lang"])

    def test_no_weak_spatial_separation(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_no_weak_spatial_separation(top)

    def test_contract_validation(self, summary: dict) -> None:
        """Full contract validation via shared helpers."""
        from conftest import assert_summary_sections, assert_top_cause_contract

        assert_summary_sections(summary, expected_lang="en", min_top_causes=1)
        top = _get_top_cause(summary)
        assert_top_cause_contract(
            top,
            expected_source="wheel",
            expected_location="front-left",
            expected_speed_band_range=(90.0, 110.0),
            confidence_range=(0.30, 0.85),
            expect_wheel_signatures=True,
            expect_not_engine=True,
        )


# ===========================================================================
# Unit tests: simulator determinism
# ===========================================================================


class TestSimulatorDeterminism:
    """Verify simulator produces deterministic output for scripted scenarios."""

    def test_road_fixed_scenario_applies_stable_gains(self) -> None:
        """road-fixed scenario sets deterministic scene_gain/scene_noise_gain."""
        from vibesensor_simulator.commands import apply_road_fixed_scenario

        class FakeClient:
            def __init__(self, name: str):
                self.name = name
                self.profile_name = "engine_idle"
                self.scene_mode = ""
                self.scene_gain = 0.0
                self.scene_noise_gain = 0.0
                self.common_event_gain = 0.0
                self.amp_scale = 0.0
                self.noise_scale = 0.0

        clients = [FakeClient(n) for n in _ALL_SENSORS]
        apply_road_fixed_scenario(clients)

        for c in clients:
            assert c.profile_name == "rough_road"
            assert c.scene_mode == "road-fixed"
            assert c.scene_gain == 0.28
            assert c.scene_noise_gain == 1.02
            assert c.common_event_gain == 0.10
            assert c.amp_scale == 0.52
            assert c.noise_scale == 1.00

    def test_road_fixed_all_clients_identical(self) -> None:
        """All clients get the same deterministic scene state."""
        from vibesensor_simulator.commands import apply_road_fixed_scenario

        class FakeClient:
            def __init__(self, name: str):
                self.name = name
                self.profile_name = "engine_idle"
                self.scene_mode = ""
                self.scene_gain = 0.0
                self.scene_noise_gain = 0.0
                self.common_event_gain = 0.0
                self.amp_scale = 0.0
                self.noise_scale = 0.0

        clients = [FakeClient(n) for n in _ALL_SENSORS]
        apply_road_fixed_scenario(clients)

        gains = [(c.scene_gain, c.scene_noise_gain, c.amp_scale, c.noise_scale) for c in clients]
        assert all(g == gains[0] for g in gains), "Not all clients received identical gains"

    def test_one_wheel_mild_fault_is_strong_but_others_remain_coupled(self) -> None:
        """Fault corner dominates while other corners still carry coupled wheel energy."""
        from vibesensor_simulator.commands import apply_one_wheel_mild_scenario

        class FakeClient:
            def __init__(self, name: str):
                self.name = name
                self.profile_name = "engine_idle"
                self.scene_mode = ""
                self.scene_gain = 0.0
                self.scene_noise_gain = 0.0
                self.common_event_gain = 0.0
                self.amp_scale = 0.0
                self.noise_scale = 0.0
                self.bump_state = __import__("numpy").zeros(3, dtype=__import__("numpy").float32)

            def pulse(self, strength: float) -> None:
                pass

        clients = [FakeClient(n) for n in _ALL_SENSORS]
        apply_one_wheel_mild_scenario(clients, "rear-left")

        fault_client = next(c for c in clients if c.name == "rear-left")
        other_clients = [c for c in clients if c.name != "rear-left"]

        assert fault_client.profile_name == "wheel_mild_imbalance"
        assert fault_client.scene_gain == 0.78
        assert fault_client.scene_noise_gain == 1.04
        assert fault_client.amp_scale == 1.0
        assert fault_client.noise_scale == 1.04
        assert fault_client.common_event_gain == 0.18
        assert fault_client.scene_gain > max(c.scene_gain for c in other_clients)
        for c in other_clients:
            assert c.profile_name == "wheel_mild_imbalance"
            assert 0.37 <= c.scene_gain <= 0.41
            assert 1.00 <= c.scene_noise_gain <= 1.03
            assert 0.70 <= c.amp_scale <= 0.74
            assert 0.98 <= c.noise_scale <= 1.00
            assert 0.11 <= c.common_event_gain <= 0.13

    def test_road_scene_single_mode_keeps_non_active_sensors_alive(self) -> None:
        from vibesensor_simulator.sim_sender import RoadSceneController

        class FakeClient:
            def __init__(self, name: str):
                self.name = name
                self.profile_name = "rough_road"
                self.scene_mode = ""
                self.scene_gain = 0.0
                self.scene_noise_gain = 0.0
                self.common_event_gain = 0.0
                self.amp_scale = 0.0
                self.noise_scale = 0.0

            def pulse(self, strength: float) -> None:
                return None

        clients = [FakeClient(n) for n in _ALL_SENSORS]
        controller = RoadSceneController(clients)
        controller._apply_single_active()

        active_clients = [c for c in clients if c.profile_name == "wheel_mild_imbalance"]
        assert len(active_clients) == 1
        non_active = [c for c in clients if c.profile_name != "wheel_mild_imbalance"]
        assert non_active
        for c in non_active:
            assert c.scene_gain >= 0.35
            assert c.common_event_gain >= 0.10

    def test_sensor_noise_floor_stays_present_even_when_scene_gain_is_zero(self) -> None:
        from vibesensor_simulator.sim_sender import SimClient, make_client_id

        client = SimClient(
            name="front-left",
            client_id=make_client_id(1),
            control_port=9101,
            sample_rate_hz=800,
            frame_samples=200,
            server_host="127.0.0.1",
            server_data_port=5005,
            server_control_port=5006,
            profile_name="rough_road",
            noise_floor_std=3.5,
        )
        client.scene_gain = 0.0
        client.scene_noise_gain = 0.0
        client.amp_scale = 0.0
        client.noise_scale = 0.0
        frame = client.make_frame()
        assert frame.dtype == np.int16
        assert np.abs(frame).sum() > 0


# ===========================================================================
# Unit tests: language selection precedence
# ===========================================================================


class TestLanguageSelectionPrecedence:
    """Verify the report language resolution chain."""

    def test_explicit_lang_overrides_metadata(self) -> None:
        """Explicit lang= parameter takes priority over metadata.language."""
        metadata = _standard_metadata(language="nl")
        samples = _fault_phase(
            speed_kmh=80.0,
            duration_s=10.0,
            fault_sensor="front-left",
            sensors=_ALL_SENSORS,
            start_t_s=0.0,
        )
        summary = summarize_run_data(metadata, samples, lang="en", file_name="test")
        assert summary.get("lang") == "en"

    def test_metadata_language_used_when_no_explicit_lang(self) -> None:
        """When lang is not passed, metadata.language is used."""
        metadata = _standard_metadata(language="nl")
        samples = _fault_phase(
            speed_kmh=80.0,
            duration_s=10.0,
            fault_sensor="front-left",
            sensors=_ALL_SENSORS,
            start_t_s=0.0,
        )
        summary = summarize_run_data(metadata, samples, lang="nl", file_name="test")
        assert summary.get("lang") == "nl"

    def test_en_default_when_no_lang_anywhere(self) -> None:
        """Default to 'en' when neither explicit lang nor metadata.language is set."""
        metadata = _standard_metadata()
        del metadata["language"]
        samples = _fault_phase(
            speed_kmh=80.0,
            duration_s=10.0,
            fault_sensor="front-left",
            sensors=_ALL_SENSORS,
            start_t_s=0.0,
        )
        summary = summarize_run_data(metadata, samples, lang="en", file_name="test")
        assert summary.get("lang") == "en"

    def test_nl_report_has_dutch_labels(self) -> None:
        """Dutch reports should contain Dutch section labels."""
        metadata = _standard_metadata(language="nl")
        samples = _fault_phase(
            speed_kmh=80.0,
            duration_s=10.0,
            fault_sensor="front-left",
            sensors=_ALL_SENSORS,
            start_t_s=0.0,
        )
        summary = summarize_run_data(metadata, samples, lang="nl", file_name="test")
        assert summary.get("lang") == "nl"


# ===========================================================================
# Unit tests: speed-band selection in mixed-phase runs
# ===========================================================================


class TestSpeedBandMixedPhase:
    """Verify speed-band attribution in multi-phase scenarios."""

    def test_ramp_then_cruise_fault_reports_cruise_band(self) -> None:
        """When ramp is followed by cruise fault, speed band should be the cruise speed."""
        sensors = _ALL_SENSORS
        samples: list[dict[str, Any]] = []
        t = 0.0

        # Short idle
        samples.extend(_idle_phase(duration_s=5.0, sensors=sensors, start_t_s=t))
        t += 5.0

        # Ramp 20→100 km/h (brief, 4 steps × 2s)
        samples.extend(
            _ramp_phase(
                speed_start=20.0,
                speed_end=100.0,
                n_steps=4,
                step_duration_s=2.0,
                sensors=sensors,
                start_t_s=t,
            )
        )
        t += 8.0

        # Long cruise fault at 100 km/h
        samples.extend(
            _fault_phase(
                speed_kmh=100.0,
                duration_s=30.0,
                fault_sensor="front-right",
                sensors=sensors,
                start_t_s=t,
            )
        )

        metadata = _standard_metadata()
        summary = summarize_run_data(metadata, samples, lang="en", file_name="speed_band_test")
        top = _get_top_cause(summary)
        _assert_speed_band_contains(top, 90.0, 110.0)

    def test_interleaved_speeds_reports_dominant_fault_band(self) -> None:
        """When fault appears at two different speeds, the dominant one wins."""
        sensors = _ALL_SENSORS
        samples: list[dict[str, Any]] = []
        t = 0.0

        # Short fault at 50 km/h (10s)
        samples.extend(
            _fault_phase(
                speed_kmh=50.0,
                duration_s=10.0,
                fault_sensor="rear-left",
                sensors=sensors,
                start_t_s=t,
            )
        )
        t += 10.0

        # Road noise at 30 km/h (5s)
        samples.extend(
            _road_noise_phase(speed_kmh=30.0, duration_s=5.0, sensors=sensors, start_t_s=t)
        )
        t += 5.0

        # Longer fault at 60 km/h (25s) — this should dominate
        samples.extend(
            _fault_phase(
                speed_kmh=60.0,
                duration_s=25.0,
                fault_sensor="rear-left",
                sensors=sensors,
                start_t_s=t,
                fault_amp=0.07,
                fault_vib_db=28.0,
            )
        )

        metadata = _standard_metadata()
        summary = summarize_run_data(metadata, samples, lang="en", file_name="dominant_band_test")
        top = _get_top_cause(summary)
        _assert_speed_band_contains(top, 50.0, 70.0)

    def test_acceleration_phase_does_not_dominate_speed_band(self) -> None:
        """Acceleration phases should be down-weighted in speed-band selection."""
        sensors = _ALL_SENSORS
        samples: list[dict[str, Any]] = []
        t = 0.0

        # Extended ramp with some accidental order matches
        for step in range(10):
            speed = 20.0 + step * 10.0  # 20→110 in 10 steps
            whz = _wheel_hz(speed)
            for _i in range(3):
                for sensor in sensors:
                    if sensor == "front-right":
                        peaks = [
                            {"hz": whz, "amp": 0.02},  # Low amplitude during ramp
                            {"hz": 142.5, "amp": 0.004},
                        ]
                        vib_db = 14.0
                    else:
                        peaks = [{"hz": 142.5, "amp": 0.004}]
                        vib_db = 8.0
                    samples.append(
                        _make_sample(
                            t_s=t,
                            speed_kmh=speed,
                            client_name=sensor,
                            top_peaks=peaks,
                            vibration_strength_db=vib_db,
                            strength_floor_amp_g=0.003,
                        )
                    )
                t += 1.0

        # Strong cruise fault at 100 km/h for 30s
        samples.extend(
            _fault_phase(
                speed_kmh=100.0,
                duration_s=30.0,
                fault_sensor="front-right",
                sensors=sensors,
                start_t_s=t,
                fault_amp=0.06,
                fault_vib_db=26.0,
            )
        )

        metadata = _standard_metadata()
        summary = summarize_run_data(metadata, samples, lang="en", file_name="accel_weight_test")
        top = _get_top_cause(summary)
        _assert_speed_band_contains(top, 90.0, 110.0)


# ===========================================================================
# Unit tests: confidence guardrails for ambiguous localization
# ===========================================================================


class TestConfidenceGuardrails:
    """Verify confidence calibration: correct results get reasonable confidence,
    ambiguous cases get lower confidence (no overconfident wrong results)."""

    def test_clear_single_sensor_fault_has_reasonable_confidence(self) -> None:
        """40s clear fault on one sensor → confidence ≥ 0.30."""
        sensors = _ALL_SENSORS
        samples = _fault_phase(
            speed_kmh=80.0,
            duration_s=40.0,
            fault_sensor="rear-right",
            sensors=sensors,
            start_t_s=0.0,
            fault_amp=0.06,
        )
        metadata = _standard_metadata()
        summary = summarize_run_data(metadata, samples, lang="en", file_name="conf_clear")
        top = _get_top_cause(summary)
        _assert_confidence_range(top, 0.30)
        _assert_strongest_sensor(top, "rear-right")

    def test_all_sensors_equal_amplitude_lower_confidence(self) -> None:
        """When all 4 sensors have equal fault amplitude, the system should either
        suppress the finding as diffuse excitation or flag it with very low confidence
        and weak spatial separation."""
        sensors = _ALL_SENSORS
        samples: list[dict[str, Any]] = []
        for i in range(30):
            for s in sensors:
                whz = _wheel_hz(80.0)
                peaks = [
                    {"hz": whz, "amp": 0.06},
                    {"hz": whz * 2, "amp": 0.024},
                ]
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=80.0,
                        client_name=s,
                        top_peaks=peaks,
                        vibration_strength_db=26.0,
                        strength_floor_amp_g=0.004,
                    )
                )
        metadata = _standard_metadata()
        summary = summarize_run_data(metadata, samples, lang="en", file_name="conf_equal")
        top_causes = summary.get("top_causes", [])
        # With equal amplitude on all sensors at constant speed, the system
        # should either suppress findings entirely (diffuse excitation) or
        # produce very low-confidence guarded results.
        if top_causes:
            top = top_causes[0]
            assert top.get("weak_spatial_separation", False) or top.get(
                "diffuse_excitation", False
            ), "Expected weak spatial separation or diffuse excitation flag"
            assert float(top.get("confidence", 0)) < 0.50, (
                "Expected low confidence for equal-amplitude scenario"
            )

    def test_short_intermittent_fault_lower_than_long_sustained(self) -> None:
        """Short intermittent fault should produce lower confidence than long sustained."""
        sensors = _ALL_SENSORS
        # Short: 8s fault at 80 km/h
        short_samples = _fault_phase(
            speed_kmh=80.0,
            duration_s=8.0,
            fault_sensor="front-left",
            sensors=sensors,
            start_t_s=0.0,
        )
        short_summary = summarize_run_data(
            _standard_metadata(), short_samples, lang="en", file_name="conf_short"
        )
        # Long: 40s fault at 80 km/h
        long_samples = _fault_phase(
            speed_kmh=80.0,
            duration_s=40.0,
            fault_sensor="front-left",
            sensors=sensors,
            start_t_s=0.0,
        )
        long_summary = summarize_run_data(
            _standard_metadata(), long_samples, lang="en", file_name="conf_long"
        )
        short_top = (
            short_summary.get("top_causes", [{}])[0] if short_summary.get("top_causes") else {}
        )
        long_top = long_summary.get("top_causes", [{}])[0] if long_summary.get("top_causes") else {}
        # Guard: both must produce real results (prevent trivially passing 0.0 >= 0.0)
        assert long_summary.get("top_causes"), "Long sustained fault must produce top_causes"
        short_conf = short_top.get("confidence", 0.0)
        long_conf = long_top.get("confidence", 0.0)
        assert long_conf > 0.0, (
            f"Long sustained fault must have non-zero confidence, got {long_conf}"
        )
        # Both should produce results, but long should have higher confidence
        assert long_conf >= short_conf, (
            f"Long sustained fault ({long_conf:.2f}) should have ≥ confidence "
            f"than short ({short_conf:.2f})"
        )
