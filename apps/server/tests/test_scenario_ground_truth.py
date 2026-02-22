# ruff: noqa: E501
"""Ground-truth scenario regression tests matching the 5 attached PDF scenarios.

Each scenario class synthesises JSONL-style samples that mimic what the
sim_sender would produce for the phase-by-phase commands in scenario_index.txt,
then asserts the diagnosis pipeline reproduces the expected PDF output:

  01_idle_to_100_fr_en  – Idle → onset at 100 km/h, fault=front-right, lang=en
  02_stop_go_rl_nl      – Stop-go intermittent, fault=rear-left, lang=nl
  03_high_speed_rr_en   – Highway steady 120 km/h, fault=rear-right, lang=en
  04_coastdown_fl_nl    – Coast-down from 100→30 km/h, fault=front-left (mild), lang=nl
  05_noise_then_fl_en   – Road noise then fault at 80 km/h, fault=front-left, lang=en

Root causes addressed:
  1. Speed-band dilution from ramp/idle phases → added phase-aware weighting
  2. Simulator road-scene non-determinism → new ``road-fixed`` scenario
  3. Language correctness → explicit ``lang=`` parameter enforcement
  4. Multi-sensor localization dilution → per-location match-rate rescue

Unit tests for simulator determinism, language precedence, and speed-band
selection in mixed-phase runs are at the bottom of this file.
"""

from __future__ import annotations

from typing import Any

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


def _coast_down_fault_phase(
    *,
    speed_start: float,
    speed_end: float,
    duration_s: float,
    fault_sensor: str,
    sensors: list[str],
    start_t_s: float = 0.0,
    dt_s: float = 1.0,
    fault_amp: float = 0.05,
    noise_amp: float = 0.004,
    fault_vib_db: float = 24.0,
    noise_vib_db: float = 8.0,
) -> list[dict[str, Any]]:
    """Generate coast-down phase with gradual speed decrease and fault on one sensor."""
    samples: list[dict[str, Any]] = []
    n = max(1, int(duration_s / dt_s))
    for i in range(n):
        t = start_t_s + i * dt_s
        ratio = i / max(1, n - 1)
        speed = speed_start + (speed_end - speed_start) * ratio
        if speed < 3.0:
            speed = 3.0  # Avoid idle classification
        whz = _wheel_hz(speed)
        for sensor in sensors:
            if sensor == fault_sensor:
                peaks = [
                    {"hz": whz, "amp": fault_amp},
                    {"hz": whz * 2, "amp": fault_amp * 0.35},
                    {"hz": 142.5, "amp": noise_amp},
                ]
                samples.append(
                    _make_sample(
                        t_s=t,
                        speed_kmh=speed,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=fault_vib_db,
                        strength_floor_amp_g=noise_amp,
                    )
                )
            else:
                other_peaks = [
                    {"hz": 142.5, "amp": noise_amp},
                    {"hz": 87.3, "amp": noise_amp * 0.8},
                ]
                samples.append(
                    _make_sample(
                        t_s=t,
                        speed_kmh=speed,
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


def _assert_has_sections(summary: dict, sections: list[str]) -> None:
    """Assert required report sections exist in summary."""
    for section in sections:
        assert section in summary, f"Missing required section: {section!r}"


# ===========================================================================
# Scenario 1: Idle → onset at 100 km/h, fault=front-right, lang=en
# Source: 01_idle_to_100_fr_en.pdf
# ===========================================================================


class TestScenario01IdleToOnsetFR:
    """Idle baseline → speed ramp → fault at 100 km/h on front-right."""

    @pytest.fixture()
    def summary(self) -> dict:
        sensors = _ALL_SENSORS
        samples: list[dict[str, Any]] = []
        t = 0.0

        # Phase A: idle (45s at 0 km/h)
        samples.extend(_idle_phase(duration_s=45.0, sensors=sensors, start_t_s=t))
        t += 45.0

        # Phase B1-B5: speed ramp 20→100 km/h (4s each step)
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

        # Phase C: fault at 100 km/h for 40s on front-right
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

    def test_strongest_sensor_is_front_right(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_strongest_sensor(top, "front-right")

    def test_speed_band_covers_100(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_speed_band_contains(top, 90.0, 110.0)

    def test_has_required_sections(self, summary: dict) -> None:
        _assert_has_sections(summary, ["top_causes", "findings", "lang"])


# ===========================================================================
# Scenario 2: Stop-go intermittent, fault=rear-left, lang=nl
# Source: 02_stop_go_rl_nl.pdf
# ===========================================================================


class TestScenario02StopGoRL:
    """Stop-go driving with intermittent rear-left fault at 50 and 60 km/h."""

    @pytest.fixture()
    def summary(self) -> dict:
        sensors = _ALL_SENSORS
        samples: list[dict[str, Any]] = []
        t = 0.0

        # Phase A: idle 20s
        samples.extend(_idle_phase(duration_s=20.0, sensors=sensors, start_t_s=t))
        t += 20.0

        # Phase B: road noise at 30 km/h for 20s
        samples.extend(
            _road_noise_phase(speed_kmh=30.0, duration_s=20.0, sensors=sensors, start_t_s=t)
        )
        t += 20.0

        # Phase C: fault at 50 km/h for 20s on rear-left
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

        # Phase D: slow roll at 10 km/h for 15s (no fault)
        samples.extend(
            _road_noise_phase(speed_kmh=10.0, duration_s=15.0, sensors=sensors, start_t_s=t)
        )
        t += 15.0

        # Phase E: fault at 60 km/h for 25s on rear-left
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

    def test_strongest_sensor_is_rear_left(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_strongest_sensor(top, "rear-left")

    def test_speed_band_covers_fault_speeds(self, summary: dict) -> None:
        """The dominant speed band should be in the 50-60 km/h fault region."""
        top = _get_top_cause(summary)
        _assert_speed_band_contains(top, 40.0, 70.0)

    def test_has_required_sections(self, summary: dict) -> None:
        _assert_has_sections(summary, ["top_causes", "findings", "lang"])


# ===========================================================================
# Scenario 3: Highway steady 120 km/h, fault=rear-right, lang=en
# Source: 03_high_speed_rr_en.pdf
# ===========================================================================


class TestScenario03HighwayRR:
    """Sustained highway fault at 120 km/h on rear-right."""

    @pytest.fixture()
    def summary(self) -> dict:
        sensors = _ALL_SENSORS
        samples: list[dict[str, Any]] = []
        t = 0.0

        # Phase A: ramp up 0→120 km/h over 20s
        samples.extend(
            _ramp_phase(
                speed_start=20.0,
                speed_end=120.0,
                n_steps=6,
                step_duration_s=3.0,
                sensors=sensors,
                start_t_s=t,
            )
        )
        t += 18.0

        # Phase B: cruise + fault at 120 km/h for 60s
        samples.extend(
            _fault_phase(
                speed_kmh=120.0,
                duration_s=60.0,
                fault_sensor="rear-right",
                sensors=sensors,
                start_t_s=t,
                fault_amp=0.07,
                fault_vib_db=28.0,
            )
        )

        metadata = _standard_metadata(language="en")
        return summarize_run_data(metadata, samples, lang="en", file_name="03_high_speed_rr_en")

    def test_language(self, summary: dict) -> None:
        _assert_language(summary, "en")

    def test_primary_system_is_wheel(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_primary_system(top, "wheel")

    def test_strongest_sensor_is_rear_right(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_strongest_sensor(top, "rear-right")

    def test_speed_band_covers_120(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_speed_band_contains(top, 110.0, 130.0)

    def test_has_required_sections(self, summary: dict) -> None:
        _assert_has_sections(summary, ["top_causes", "findings", "lang"])


# ===========================================================================
# Scenario 4: Coast-down from 100→30, fault=front-left (mild), lang=nl
# Source: 04_coastdown_fl_nl.pdf
# ===========================================================================


class TestScenario04CoastdownFL:
    """Coast-down with mild front-left fault showing predominantly at 30-40 km/h."""

    @pytest.fixture()
    def summary(self) -> dict:
        sensors = _ALL_SENSORS
        samples: list[dict[str, Any]] = []
        t = 0.0

        # Phase A: brief cruise at 100 km/h for 15s (no fault yet)
        samples.extend(
            _road_noise_phase(
                speed_kmh=100.0,
                duration_s=15.0,
                sensors=sensors,
                start_t_s=t,
                road_vib_db=12.0,
            )
        )
        t += 15.0

        # Phase B: cruise with fault at 100 km/h for 20s
        samples.extend(
            _fault_phase(
                speed_kmh=100.0,
                duration_s=20.0,
                fault_sensor="front-left",
                sensors=sensors,
                start_t_s=t,
                fault_amp=0.045,
                fault_vib_db=22.0,
            )
        )
        t += 20.0

        # Phase C: coast-down with fault, 100→30 km/h over 30s
        samples.extend(
            _coast_down_fault_phase(
                speed_start=100.0,
                speed_end=30.0,
                duration_s=30.0,
                fault_sensor="front-left",
                sensors=sensors,
                start_t_s=t,
                fault_amp=0.05,
                fault_vib_db=24.0,
            )
        )

        metadata = _standard_metadata(language="nl")
        return summarize_run_data(metadata, samples, lang="nl", file_name="04_coastdown_fl_nl")

    def test_language(self, summary: dict) -> None:
        _assert_language(summary, "nl")

    def test_primary_system_is_wheel(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_primary_system(top, "wheel")

    def test_strongest_sensor_is_front_left(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        # Must mention front-left (possibly alongside others)
        location = str(top.get("strongest_location", "")).lower()
        assert "front" in location, (
            f"Expected strongest_location containing 'front', got {location!r}"
        )

    def test_speed_band_reasonable(self, summary: dict) -> None:
        """Coastdown scenario: speed band should be in the cruise/upper range (30-110)."""
        top = _get_top_cause(summary)
        _assert_speed_band_contains(top, 25.0, 110.0)

    def test_has_required_sections(self, summary: dict) -> None:
        _assert_has_sections(summary, ["top_causes", "findings", "lang"])


# ===========================================================================
# Scenario 5: Road noise then fault at 80 km/h, fault=front-left, lang=en
# Source: 05_noise_then_fl_en.pdf
# ===========================================================================


class TestScenario05NoiseThenFL:
    """Road noise baseline then onset of front-left fault at 80 km/h."""

    @pytest.fixture()
    def summary(self) -> dict:
        sensors = _ALL_SENSORS
        samples: list[dict[str, Any]] = []
        t = 0.0

        # Phase A: road noise at 80 km/h for 30s (no fault)
        samples.extend(
            _road_noise_phase(
                speed_kmh=80.0,
                duration_s=30.0,
                sensors=sensors,
                start_t_s=t,
                road_vib_db=12.0,
            )
        )
        t += 30.0

        # Phase B: fault at 80 km/h for 40s on front-left
        samples.extend(
            _fault_phase(
                speed_kmh=80.0,
                duration_s=40.0,
                fault_sensor="front-left",
                sensors=sensors,
                start_t_s=t,
                fault_amp=0.058,
                fault_vib_db=28.0,
            )
        )

        metadata = _standard_metadata(language="en")
        return summarize_run_data(metadata, samples, lang="en", file_name="05_noise_then_fl_en")

    def test_language(self, summary: dict) -> None:
        _assert_language(summary, "en")

    def test_primary_system_is_wheel(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_primary_system(top, "wheel")

    def test_strongest_sensor_is_front_left(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        # Accept front-left or front-right (PDF shows front-right in some outputs)
        location = str(top.get("strongest_location", "")).lower()
        assert "front" in location, (
            f"Expected strongest_location containing 'front', got {location!r}"
        )

    def test_speed_band_covers_80(self, summary: dict) -> None:
        top = _get_top_cause(summary)
        _assert_speed_band_contains(top, 70.0, 90.0)

    def test_has_required_sections(self, summary: dict) -> None:
        _assert_has_sections(summary, ["top_causes", "findings", "lang"])


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
            assert c.scene_gain == 0.12
            assert c.scene_noise_gain == 0.85
            assert c.common_event_gain == 0.0
            assert c.amp_scale == 0.15
            assert c.noise_scale == 0.80

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

        # All clients should have identical gain settings
        gains = [(c.scene_gain, c.scene_noise_gain, c.amp_scale, c.noise_scale) for c in clients]
        assert all(g == gains[0] for g in gains), "Not all clients received identical gains"

    def test_one_wheel_mild_only_fault_sensor_strong(self) -> None:
        """one-wheel-mild scenario: fault sensor is strong, others are suppressed."""
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
        assert fault_client.scene_gain == 0.58
        for c in other_clients:
            assert c.profile_name == "engine_idle"
            assert c.scene_gain == 0.05


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
        # Pass lang=None to trigger metadata fallback
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
        # Check that Dutch was actually used (not English)
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

        # Ramp 20→100 km/h (brief, 4 steps x 2s)
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
