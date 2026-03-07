# ruff: noqa: E501
from __future__ import annotations

from typing import Any

from _phased_scenario_helpers import assert_finding_location
from _phased_scenario_helpers import assert_finding_source
from _phased_scenario_helpers import build_fault_samples_at_speed
from _phased_scenario_helpers import build_speed_sweep_fault_samples
from _phased_scenario_helpers import extract_top_finding
from _phased_scenario_helpers import make_sample
from _phased_scenario_helpers import parse_speed_band
from _phased_scenario_helpers import standard_metadata
from _phased_scenario_helpers import summarize_run_data
from _phased_scenario_helpers import wheel_hz


class TestScenario1IdleToSpeedUp:
    def test_correct_corner_identified(self) -> None:
        meta = standard_metadata()
        idle_samples: list[dict[str, Any]] = []
        for i in range(10):
            for sensor in ["front-left", "front-right", "rear-left", "rear-right"]:
                idle_samples.append(make_sample(t_s=float(i), speed_kmh=0.0, client_name=sensor, top_peaks=[{"hz": 13.0, "amp": 0.003}], vibration_strength_db=5.0))
        ramp_samples = build_speed_sweep_fault_samples(speed_start_kmh=20.0, speed_end_kmh=100.0, fault_sensor="front-right", other_sensors=["front-left", "rear-left", "rear-right"], n_samples=8, dt_s=2.0, start_t_s=10.0, fault_amp=0.015, fault_vib_db=14.0)
        fault_samples = build_fault_samples_at_speed(speed_kmh=100.0, fault_sensor="front-right", other_sensors=["front-left", "rear-left", "rear-right"], n_samples=40, dt_s=1.0, start_t_s=26.0, fault_amp=0.06, fault_vib_db=24.0)
        summary = summarize_run_data(meta, idle_samples + ramp_samples + fault_samples, include_samples=False)
        assert_finding_location(summary, "front-right", "Scenario 1")

    def test_correct_system_identified(self) -> None:
        summary = summarize_run_data(standard_metadata(), build_fault_samples_at_speed(speed_kmh=100.0, fault_sensor="front-right", other_sensors=["front-left", "rear-left", "rear-right"], n_samples=40, fault_amp=0.06, fault_vib_db=24.0), include_samples=False)
        assert_finding_source(summary, label="Scenario 1")

    def test_correct_speed_band(self) -> None:
        summary = summarize_run_data(standard_metadata(), build_fault_samples_at_speed(speed_kmh=100.0, fault_sensor="front-right", other_sensors=["front-left", "rear-left", "rear-right"], n_samples=40, fault_amp=0.06, fault_vib_db=24.0), include_samples=False)
        band_low, band_high = parse_speed_band(extract_top_finding(summary))
        assert band_low >= 80.0 and band_high <= 130.0


class TestScenario2StopGoIntermittent:
    def test_correct_corner_rear_left(self) -> None:
        meta = standard_metadata()
        samples: list[dict[str, Any]] = []
        t = 0.0
        sensors = ["front-left", "front-right", "rear-left", "rear-right"]
        for _ in range(8):
            for sensor in sensors:
                samples.append(make_sample(t_s=t, speed_kmh=0.0, client_name=sensor, top_peaks=[{"hz": 13.0, "amp": 0.003}], vibration_strength_db=5.0))
            t += 1.0
        for _ in range(10):
            for sensor in sensors:
                samples.append(make_sample(t_s=t, speed_kmh=30.0, client_name=sensor, top_peaks=[{"hz": 87.3, "amp": 0.004}], vibration_strength_db=8.0))
            t += 1.0
        samples.extend(build_fault_samples_at_speed(speed_kmh=50.0, fault_sensor="rear-left", other_sensors=["front-left", "front-right", "rear-right"], n_samples=15, start_t_s=t, fault_amp=0.05, fault_vib_db=22.0))
        t += 15.0
        for _ in range(8):
            for sensor in sensors:
                samples.append(make_sample(t_s=t, speed_kmh=10.0, client_name=sensor, top_peaks=[{"hz": 87.3, "amp": 0.003}], vibration_strength_db=6.0))
            t += 1.0
        samples.extend(build_fault_samples_at_speed(speed_kmh=60.0, fault_sensor="rear-left", other_sensors=["front-left", "front-right", "rear-right"], n_samples=20, start_t_s=t, fault_amp=0.055, fault_vib_db=23.0))
        assert_finding_location(summarize_run_data(meta, samples, include_samples=False), "rear-left", "Scenario 2")

    def test_system_is_wheel_not_engine(self) -> None:
        summary = summarize_run_data(standard_metadata(), build_fault_samples_at_speed(speed_kmh=55.0, fault_sensor="rear-left", other_sensors=["front-left", "front-right", "rear-right"], n_samples=30, fault_amp=0.05, fault_vib_db=22.0), include_samples=False)
        assert_finding_source(summary, label="Scenario 2")

    def test_speed_band_covers_50_60(self) -> None:
        samples_50 = build_fault_samples_at_speed(speed_kmh=50.0, fault_sensor="rear-left", other_sensors=["front-left", "front-right", "rear-right"], n_samples=20, start_t_s=0.0, fault_amp=0.05, fault_vib_db=22.0)
        samples_60 = build_fault_samples_at_speed(speed_kmh=60.0, fault_sensor="rear-left", other_sensors=["front-left", "front-right", "rear-right"], n_samples=20, start_t_s=20.0, fault_amp=0.055, fault_vib_db=23.0)
        speed_band = str(extract_top_finding(summarize_run_data(standard_metadata(), samples_50 + samples_60, include_samples=False)).get("strongest_speed_band") or "")
        band_low = 0
        for part in speed_band.replace("km/h", "").split("-"):
            try:
                band_low = int(part.strip())
                break
            except ValueError:
                continue
        assert band_low >= 40


class TestScenario3HighwayRearRight:
    def test_correct_corner_rear_right(self) -> None:
        all_samples = build_fault_samples_at_speed(speed_kmh=60.0, fault_sensor="rear-right", other_sensors=["front-left", "front-right", "rear-left"], n_samples=10, start_t_s=0.0, fault_amp=0.004, noise_amp=0.003, fault_vib_db=8.0, noise_vib_db=7.0)
        all_samples += build_fault_samples_at_speed(speed_kmh=90.0, fault_sensor="rear-right", other_sensors=["front-left", "front-right", "rear-left"], n_samples=10, start_t_s=10.0, fault_amp=0.004, noise_amp=0.003, fault_vib_db=8.0, noise_vib_db=7.0)
        all_samples += build_fault_samples_at_speed(speed_kmh=120.0, fault_sensor="rear-right", other_sensors=["front-left", "front-right", "rear-left"], n_samples=30, start_t_s=20.0, fault_amp=0.07, fault_vib_db=26.0)
        all_samples += build_fault_samples_at_speed(speed_kmh=100.0, fault_sensor="rear-right", other_sensors=["front-left", "front-right", "rear-left"], n_samples=10, start_t_s=50.0, fault_amp=0.004, noise_amp=0.003, fault_vib_db=8.0, noise_vib_db=7.0)
        assert_finding_location(summarize_run_data(standard_metadata(), all_samples, include_samples=False), "rear-right", "Scenario 3")

    def test_speed_band_covers_120(self) -> None:
        summary = summarize_run_data(standard_metadata(), build_fault_samples_at_speed(speed_kmh=120.0, fault_sensor="rear-right", other_sensors=["front-left", "front-right", "rear-left"], n_samples=35, fault_amp=0.07, fault_vib_db=26.0), include_samples=False)
        band_low, band_high = parse_speed_band(extract_top_finding(summary))
        assert band_low >= 100.0 and band_high <= 140.0


class TestScenario4CoastDownMidRange:
    @staticmethod
    def build_coast_down_samples(*, add_harmonic: bool = True) -> list[dict[str, Any]]:
        samples: list[dict[str, Any]] = []
        t = 0.0
        for i in range(50):
            speed = 110.0 - i * 1.6
            whz = wheel_hz(speed)
            mid_strength = max(0.0, 1.0 - abs(speed - 80.0) / 40.0)
            fault_amp = 0.01 + 0.06 * mid_strength
            fault_vib_db = 10.0 + 16.0 * mid_strength
            fault_peaks: list[dict[str, float]] = [{"hz": whz, "amp": fault_amp}]
            if add_harmonic:
                fault_peaks.append({"hz": whz * 2, "amp": fault_amp * 0.3})
            fault_peaks.append({"hz": 142.5, "amp": 0.003})
            samples.append(make_sample(t_s=t, speed_kmh=speed, client_name="front-left", top_peaks=fault_peaks, vibration_strength_db=fault_vib_db, strength_floor_amp_g=0.003))
            for other in ["front-right", "rear-left", "rear-right"]:
                samples.append(make_sample(t_s=t, speed_kmh=speed, client_name=other, top_peaks=[{"hz": 142.5, "amp": 0.003}, {"hz": 87.3, "amp": 0.003}], vibration_strength_db=8.0, strength_floor_amp_g=0.003))
            t += 1.0
        return samples

    def test_correct_corner_front_left(self) -> None:
        assert_finding_location(summarize_run_data(standard_metadata(), self.build_coast_down_samples(add_harmonic=True), include_samples=False), "front-left", "Scenario 4")

    def test_speed_band_emphasizes_midrange(self) -> None:
        speed_band = str(extract_top_finding(summarize_run_data(standard_metadata(), self.build_coast_down_samples(add_harmonic=False), include_samples=False)).get("strongest_speed_band") or "")
        assert any(str(speed) in speed_band for speed in [70, 80, 90])


class TestScenario5MixedNoiseThenFault:
    def test_correct_corner_front_left(self) -> None:
        meta = standard_metadata()
        noise_samples: list[dict[str, Any]] = []
        for i in range(25):
            for sensor in ["front-left", "front-right", "rear-left", "rear-right"]:
                noise_samples.append(make_sample(t_s=float(i), speed_kmh=80.0, client_name=sensor, top_peaks=[{"hz": 87.3, "amp": 0.005}, {"hz": 142.5, "amp": 0.004}], vibration_strength_db=10.0, strength_floor_amp_g=0.004))
        fault = build_fault_samples_at_speed(speed_kmh=100.0, fault_sensor="front-left", other_sensors=["front-right", "rear-left", "rear-right"], n_samples=35, start_t_s=25.0, fault_amp=0.06, fault_vib_db=24.0)
        assert_finding_location(summarize_run_data(meta, noise_samples + fault, include_samples=False), "front-left", "Scenario 5")