from __future__ import annotations

import pytest
from test_support import (
    assert_finding_location,
    build_fault_samples_at_speed,
    build_speed_sweep_fault_samples,
    extract_top_finding,
    make_sample,
    standard_metadata,
    wheel_hz,
)

from vibesensor.use_cases.diagnostics import summarize_run_data
from vibesensor.use_cases.diagnostics.findings import _classify_peak_type


class TestSpeedBandAttribution:
    def test_speed_band_matches_fault_speed_not_overall(self) -> None:
        baseline = build_fault_samples_at_speed(
            speed_kmh=60.0,
            fault_sensor="front-right",
            other_sensors=["front-left", "rear-left", "rear-right"],
            n_samples=15,
            start_t_s=0.0,
            fault_amp=0.003,
            noise_amp=0.003,
            fault_vib_db=6.0,
            noise_vib_db=6.0,
        )
        fault = build_fault_samples_at_speed(
            speed_kmh=120.0,
            fault_sensor="front-right",
            other_sensors=["front-left", "rear-left", "rear-right"],
            n_samples=30,
            start_t_s=15.0,
            fault_amp=0.07,
            fault_vib_db=26.0,
        )
        cool = build_fault_samples_at_speed(
            speed_kmh=100.0,
            fault_sensor="front-right",
            other_sensors=["front-left", "rear-left", "rear-right"],
            n_samples=10,
            start_t_s=45.0,
            fault_amp=0.003,
            noise_amp=0.003,
            fault_vib_db=6.0,
            noise_vib_db=6.0,
        )
        speed_band = str(
            extract_top_finding(
                summarize_run_data(
                    standard_metadata(),
                    baseline + fault + cool,
                    include_samples=False,
                ),
            ).get("strongest_speed_band")
            or "",
        )
        assert "120" in speed_band or "110" in speed_band


class TestWheelVsEngineDrivelineGating:
    def test_wheel_1x_not_misclassified_as_engine(self) -> None:
        top = extract_top_finding(
            summarize_run_data(
                standard_metadata(),
                build_speed_sweep_fault_samples(
                    speed_start_kmh=40.0,
                    speed_end_kmh=120.0,
                    fault_sensor="front-right",
                    other_sensors=["front-left", "rear-left", "rear-right"],
                    n_samples=50,
                    fault_amp=0.06,
                    fault_vib_db=24.0,
                ),
                include_samples=False,
            ),
        )
        assert "engine" not in str(top.get("suspected_source") or "").lower()

    def test_constant_speed_wheel_not_engine(self) -> None:
        findings = [
            f
            for f in summarize_run_data(
                standard_metadata(),
                build_fault_samples_at_speed(
                    speed_kmh=80.0,
                    fault_sensor="rear-left",
                    other_sensors=["front-left", "front-right", "rear-right"],
                    n_samples=40,
                    fault_amp=0.05,
                    fault_vib_db=22.0,
                ),
                include_samples=False,
            ).get("findings", [])
            if isinstance(f, dict) and not str(f.get("finding_id", "")).startswith("REF_")
        ]
        if findings:
            source = str(
                max(findings, key=lambda f: float(f.get("confidence") or 0)).get(
                    "suspected_source",
                )
                or "",
            ).lower()
            assert "wheel" in source or "tire" in source or "unknown" in source


class TestConfidenceWithSpatialAmbiguity:
    def test_equal_amplitude_all_sensors_low_confidence(self) -> None:
        samples = []
        for i in range(30):
            speed = 60.0 + i * 1.0
            whz = wheel_hz(speed)
            for sensor in ["front-left", "front-right", "rear-left", "rear-right"]:
                samples.append(
                    make_sample(
                        t_s=float(i),
                        speed_kmh=speed,
                        client_name=sensor,
                        top_peaks=[
                            {"hz": whz, "amp": 0.05},
                            {"hz": whz * 2, "amp": 0.02},
                            {"hz": 142.5, "amp": 0.003},
                        ],
                        vibration_strength_db=22.0,
                        strength_floor_amp_g=0.003,
                    ),
                )
        conf = float(
            extract_top_finding(
                summarize_run_data(standard_metadata(), samples, include_samples=False),
            ).get("confidence")
            or 0,
        )
        assert conf < 0.70

    def test_single_sensor_dominant_higher_confidence(self) -> None:
        conf = float(
            extract_top_finding(
                summarize_run_data(
                    standard_metadata(),
                    build_speed_sweep_fault_samples(
                        speed_start_kmh=50.0,
                        speed_end_kmh=110.0,
                        fault_sensor="front-right",
                        other_sensors=["front-left", "rear-left", "rear-right"],
                        n_samples=40,
                        fault_amp=0.08,
                        noise_amp=0.003,
                        fault_vib_db=26.0,
                        noise_vib_db=6.0,
                    ),
                    include_samples=False,
                ),
            ).get("confidence")
            or 0,
        )
        assert conf >= 0.40


class TestTransientDeWeighting:
    def test_transient_classified_correctly(self) -> None:
        assert _classify_peak_type(0.10, 8.0) == "transient"
        assert _classify_peak_type(0.05, 2.0) == "transient"

    def test_patterned_classified_correctly(self) -> None:
        assert _classify_peak_type(0.50, 2.0) == "patterned"
        assert _classify_peak_type(0.80, 1.5) == "patterned"

    def test_baseline_noise_classified(self) -> None:
        assert _classify_peak_type(0.60, 1.5, snr=1.0) == "baseline_noise"


class TestLocalizationStability:
    ALL_SENSORS = ["front-left", "front-right", "rear-left", "rear-right"]

    @pytest.mark.parametrize("fault_sensor", ALL_SENSORS)
    def test_localization_stable_with_clear_dominance(self, fault_sensor: str) -> None:
        others = [sensor for sensor in self.ALL_SENSORS if sensor != fault_sensor]
        summary = summarize_run_data(
            standard_metadata(),
            build_speed_sweep_fault_samples(
                speed_start_kmh=50.0,
                speed_end_kmh=100.0,
                fault_sensor=fault_sensor,
                other_sensors=others,
                n_samples=40,
                fault_amp=0.06,
                noise_amp=0.003,
                fault_vib_db=24.0,
                noise_vib_db=6.0,
            ),
            include_samples=False,
        )
        assert_finding_location(summary, fault_sensor, f"Localization({fault_sensor})")
