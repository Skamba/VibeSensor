# ruff: noqa: E501
"""Tests for source-aware localization, diffuse excitation detection,
no-fault suppression, and confidence calibration.

These tests validate the fixes for false localization (non-wheel sensors
assigned as wheel fault sources), false-positive wheel findings (no-fault
scenarios producing diagnoses), and diffuse excitation detection.
"""

from __future__ import annotations

from typing import Any

import pytest

from vibesensor.locations import WHEEL_LOCATION_CODES, is_wheel_location
from vibesensor.report.summary import build_findings_for_samples, summarize_run_data
from vibesensor.report.test_plan import _location_speedbin_summary

# ---------------------------------------------------------------------------
# Helpers (reused from test_scenario_ground_truth patterns)
# ---------------------------------------------------------------------------
_TIRE_CIRCUMFERENCE_M = 2.036


def _wheel_hz(speed_kmh: float) -> float:
    speed_m_s = speed_kmh / 3.6
    return speed_m_s / _TIRE_CIRCUMFERENCE_M


def _standard_metadata(**overrides: Any) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "tire_circumference_m": _TIRE_CIRCUMFERENCE_M,
        "raw_sample_rate_hz": 1000,
        "final_drive_ratio": 3.73,
        "current_gear_ratio": 0.64,
        "sensor_model": "ADXL345",
        "units": {"accel_x_g": "g", "accel_y_g": "g", "accel_z_g": "g"},
        "language": "en",
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
) -> dict[str, Any]:
    amp = max((p.get("amp", 0.01) for p in top_peaks), default=0.01)
    return {
        "record_type": "sample",
        "t_s": t_s,
        "speed_kmh": speed_kmh,
        "accel_x_g": amp,
        "accel_y_g": amp * 0.5,
        "accel_z_g": amp * 0.3,
        "vibration_strength_db": vibration_strength_db,
        "strength_bucket": "l2" if vibration_strength_db < 20 else "l3",
        "strength_floor_amp_g": strength_floor_amp_g,
        "top_peaks": top_peaks,
        "client_name": client_name,
        "client_id": client_name,
    }


_ALL_WHEEL_SENSORS = ["front-left", "front-right", "rear-left", "rear-right"]
_MIXED_SENSORS = ["front-left", "front-right", "rear-left", "rear-right", "driver-seat", "trunk"]
_CABIN_SENSORS = ["driver-seat", "front-passenger", "rear-left-seat"]


# ---------------------------------------------------------------------------
# 1. Sensor-type classification tests
# ---------------------------------------------------------------------------


class TestSensorTypeClassification:
    """is_wheel_location must correctly classify all location variants."""

    @pytest.mark.parametrize(
        "label",
        [
            "front-left",
            "front-right",
            "rear-left",
            "rear-right",
            "Front Left",
            "Front Right",
            "Rear Left",
            "Rear Right",
            "front_left_wheel",
            "front_right_wheel",
            "rear_left_wheel",
            "rear_right_wheel",
            "FL Wheel",
            "FR Wheel",
            "RL Wheel",
            "RR Wheel",
        ],
    )
    def test_wheel_locations_detected(self, label: str) -> None:
        assert is_wheel_location(label), f"Expected {label!r} to be classified as wheel"

    @pytest.mark.parametrize(
        "label",
        [
            "driver-seat",
            "Driver Seat",
            "trunk",
            "Trunk",
            "engine_bay",
            "Engine Bay",
            "transmission",
            "Transmission",
            "driveshaft_tunnel",
            "front_subframe",
            "rear_subframe",
            "front-passenger",
            "rear-left-seat",
            "rear-center-seat",
        ],
    )
    def test_non_wheel_locations_not_detected(self, label: str) -> None:
        assert not is_wheel_location(label), f"Expected {label!r} NOT to be classified as wheel"

    def test_empty_and_none(self) -> None:
        assert not is_wheel_location("")
        assert not is_wheel_location("   ")

    def test_wheel_location_codes_are_complete(self) -> None:
        assert len(WHEEL_LOCATION_CODES) == 4
        for code in WHEEL_LOCATION_CODES:
            assert is_wheel_location(code)


# ---------------------------------------------------------------------------
# 2. Source-aware localization tests
# ---------------------------------------------------------------------------


class TestSourceAwareLocalization:
    """Wheel diagnoses must prioritize wheel/corner sensors as fault sources."""

    def test_wheel_diagnosis_prefers_wheel_sensor_over_cabin(self) -> None:
        """When cabin sensor has higher amplitude but wheel sensors are present,
        wheel sensor should be selected as fault source for wheel/tire diagnoses."""
        matches = []
        for i in range(20):
            speed = 60.0 + i * 2
            whz = _wheel_hz(speed)
            # Cabin sensor: stronger signal
            matches.append(
                {
                    "speed_kmh": speed,
                    "amp": 0.08,
                    "location": "Driver Seat",
                    "matched_hz": whz,
                    "rel_error": 0.02,
                }
            )
            # Wheel sensor: slightly weaker but valid
            matches.append(
                {
                    "speed_kmh": speed,
                    "amp": 0.06,
                    "location": "Front Left",
                    "matched_hz": whz,
                    "rel_error": 0.01,
                }
            )

        _, hotspot = _location_speedbin_summary(
            matches,
            lang="en",
            suspected_source="wheel/tire",
        )
        assert hotspot is not None
        top_location = str(hotspot.get("top_location", ""))
        assert is_wheel_location(top_location), (
            f"Wheel diagnosis assigned to non-wheel sensor: {top_location}"
        )

    def test_non_wheel_source_allows_any_location(self) -> None:
        """For non-wheel diagnoses (e.g., engine), any sensor can be fault source."""
        matches = []
        for i in range(20):
            speed = 60.0 + i * 2
            matches.append(
                {
                    "speed_kmh": speed,
                    "amp": 0.08,
                    "location": "Engine Bay",
                    "matched_hz": 25.0,
                    "rel_error": 0.02,
                }
            )
            matches.append(
                {
                    "speed_kmh": speed,
                    "amp": 0.04,
                    "location": "Front Left",
                    "matched_hz": 25.0,
                    "rel_error": 0.03,
                }
            )

        _, hotspot = _location_speedbin_summary(
            matches,
            lang="en",
            suspected_source="engine",
        )
        assert hotspot is not None
        top_location = str(hotspot.get("top_location", ""))
        assert top_location == "Engine Bay"

    def test_no_wheel_sensors_falls_back_to_strongest(self) -> None:
        """If only cabin/chassis sensors are present, use strongest available."""
        matches = []
        for i in range(15):
            speed = 50.0 + i * 3
            whz = _wheel_hz(speed)
            matches.append(
                {
                    "speed_kmh": speed,
                    "amp": 0.07,
                    "location": "Driver Seat",
                    "matched_hz": whz,
                    "rel_error": 0.02,
                }
            )
            matches.append(
                {
                    "speed_kmh": speed,
                    "amp": 0.03,
                    "location": "Trunk",
                    "matched_hz": whz,
                    "rel_error": 0.03,
                }
            )

        _, hotspot = _location_speedbin_summary(
            matches,
            lang="en",
            suspected_source="wheel/tire",
        )
        assert hotspot is not None
        # No wheel sensors available, so it should fall back to strongest
        top_location = str(hotspot.get("top_location", ""))
        assert top_location == "Driver Seat"


# ---------------------------------------------------------------------------
# 3. Diffuse excitation detection tests
# ---------------------------------------------------------------------------


class TestDiffuseExcitationDetection:
    """Diffuse/global excitation should not produce corner-specific wheel diagnosis."""

    def test_uniform_peaks_all_sensors_flags_diffuse(self) -> None:
        """When all sensors show identical peaks, the finding should be flagged
        as diffuse excitation with reduced confidence."""
        sensors = _ALL_WHEEL_SENSORS
        samples: list[dict[str, Any]] = []
        # Use varying speed to avoid constant-speed filter
        for i in range(40):
            for s in sensors:
                speed = 50.0 + i * 1.5
                whz = _wheel_hz(speed)
                peaks = [{"hz": whz, "amp": 0.05}, {"hz": whz * 2, "amp": 0.02}]
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=speed,
                        client_name=s,
                        top_peaks=peaks,
                        vibration_strength_db=24.0,
                    )
                )
        metadata = _standard_metadata()
        findings = build_findings_for_samples(metadata=metadata, samples=samples, lang="en")
        order_findings = [
            f
            for f in findings
            if not str(f.get("finding_id", "")).startswith("REF_")
            and str(f.get("finding_key", "")).startswith("wheel_")
        ]
        # If any order finding exists, it should be flagged as diffuse
        for f in order_findings:
            assert f.get("diffuse_excitation") is True, (
                f"Expected diffuse_excitation flag for uniform-amplitude finding: {f.get('finding_key')}"
            )

    def test_single_sensor_fault_not_flagged_diffuse(self) -> None:
        """When only one sensor has matching peaks, should NOT be flagged diffuse."""
        sensors = _ALL_WHEEL_SENSORS
        samples: list[dict[str, Any]] = []
        for i in range(40):
            speed = 50.0 + i * 1.5
            whz = _wheel_hz(speed)
            for s in sensors:
                if s == "front-right":
                    peaks = [{"hz": whz, "amp": 0.08}, {"hz": whz * 2, "amp": 0.03}]
                    vib_db = 28.0
                else:
                    peaks = [{"hz": 15.0, "amp": 0.005}]
                    vib_db = 10.0
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=speed,
                        client_name=s,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                    )
                )
        metadata = _standard_metadata()
        findings = build_findings_for_samples(metadata=metadata, samples=samples, lang="en")
        order_findings = [
            f
            for f in findings
            if not str(f.get("finding_id", "")).startswith("REF_")
            and str(f.get("finding_key", "")).startswith("wheel_")
        ]
        for f in order_findings:
            assert f.get("diffuse_excitation") is not True, (
                "Single-sensor fault should NOT be flagged as diffuse"
            )


# ---------------------------------------------------------------------------
# 4. No-fault suppression tests
# ---------------------------------------------------------------------------


class TestNoFaultSuppression:
    """No-fault scenarios must not produce high-confidence wheel diagnoses."""

    def test_idle_only_no_wheel_diagnosis(self) -> None:
        """Pure idle samples should not produce a wheel diagnosis."""
        sensors = _ALL_WHEEL_SENSORS
        samples: list[dict[str, Any]] = []
        for i in range(20):
            for s in sensors:
                peaks = [{"hz": 12.0, "amp": 0.003}]
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=0.0,
                        client_name=s,
                        top_peaks=peaks,
                        vibration_strength_db=6.0,
                    )
                )
        metadata = _standard_metadata()
        summary = summarize_run_data(metadata, samples, lang="en", file_name="idle_only")
        top_causes = summary.get("top_causes", [])
        # No wheel/tire diagnosis should appear for idle-only data
        wheel_causes = [c for c in top_causes if str(c.get("source", "")) == "wheel/tire"]
        assert len(wheel_causes) == 0, (
            f"Idle-only scenario produced wheel diagnosis: {wheel_causes}"
        )

    def test_road_noise_no_specific_fault(self) -> None:
        """Road noise on all sensors should not produce a confident wheel finding."""
        sensors = _ALL_WHEEL_SENSORS
        samples: list[dict[str, Any]] = []
        for i in range(30):
            speed = 40.0 + i * 2
            for s in sensors:
                # Random broadband road noise, not matching any specific order
                peaks = [
                    {"hz": 8.0 + i * 0.3, "amp": 0.01},
                    {"hz": 15.0, "amp": 0.008},
                    {"hz": 34.0, "amp": 0.005},
                ]
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=speed,
                        client_name=s,
                        top_peaks=peaks,
                        vibration_strength_db=14.0,
                    )
                )
        metadata = _standard_metadata()
        summary = summarize_run_data(metadata, samples, lang="en", file_name="road_noise")
        top_causes = summary.get("top_causes", [])
        for c in top_causes:
            if str(c.get("source", "")) == "wheel/tire":
                conf = float(c.get("confidence", 0))
                assert conf < 0.50, f"Road noise produced confident wheel diagnosis: {conf:.2f}"


# ---------------------------------------------------------------------------
# 5. Confidence calibration across sensor counts
# ---------------------------------------------------------------------------


class TestConfidenceCalibration:
    """Confidence must be calibrated for 1-12 sensors."""

    def _build_fault_samples(
        self,
        sensors: list[str],
        fault_sensor: str,
        n_samples: int = 30,
    ) -> list[dict[str, Any]]:
        """Build samples with a clear fault on one sensor."""
        samples: list[dict[str, Any]] = []
        for i in range(n_samples):
            speed = 50.0 + i * 1.5
            whz = _wheel_hz(speed)
            for s in sensors:
                if s == fault_sensor:
                    peaks = [{"hz": whz, "amp": 0.08}, {"hz": whz * 2, "amp": 0.03}]
                    vib_db = 28.0
                else:
                    peaks = [{"hz": 15.0, "amp": 0.005}]
                    vib_db = 10.0
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=speed,
                        client_name=s,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                    )
                )
        return samples

    def test_single_sensor_produces_finding(self) -> None:
        """A single sensor with a clear fault should still produce a finding."""
        samples = self._build_fault_samples(["front-right"], "front-right")
        metadata = _standard_metadata()
        findings = build_findings_for_samples(metadata=metadata, samples=samples, lang="en")
        wheel_findings = [f for f in findings if str(f.get("finding_key", "")).startswith("wheel_")]
        assert len(wheel_findings) > 0, "Single sensor should produce a wheel finding"

    def test_four_sensor_clear_fault(self) -> None:
        """4 sensors with a clear single-sensor fault should identify correct location."""
        sensors = _ALL_WHEEL_SENSORS
        samples = self._build_fault_samples(sensors, "front-right")
        metadata = _standard_metadata()
        findings = build_findings_for_samples(metadata=metadata, samples=samples, lang="en")
        wheel_findings = [f for f in findings if str(f.get("finding_key", "")).startswith("wheel_")]
        assert len(wheel_findings) > 0, "4-sensor setup should produce a wheel finding"
        top = wheel_findings[0]
        strongest = str(top.get("strongest_location", "")).lower()
        assert "right" in strongest or "fr" in strongest, f"Expected front-right, got {strongest}"

    def test_eight_sensor_mixed_clear_fault(self) -> None:
        """8 mixed sensors with a clear wheel fault should still identify the wheel."""
        sensors = [
            "front-left",
            "front-right",
            "rear-left",
            "rear-right",
            "driver-seat",
            "trunk",
            "engine-bay",
            "transmission",
        ]
        samples = self._build_fault_samples(sensors, "rear-left")
        metadata = _standard_metadata()
        findings = build_findings_for_samples(metadata=metadata, samples=samples, lang="en")
        wheel_findings = [f for f in findings if str(f.get("finding_key", "")).startswith("wheel_")]
        assert len(wheel_findings) > 0, "8-sensor setup should produce a wheel finding"
        top = wheel_findings[0]
        strongest = str(top.get("strongest_location", "")).lower()
        assert "rear" in strongest and "left" in strongest, f"Expected rear-left, got {strongest}"


# ---------------------------------------------------------------------------
# 6. Unit consistency tests
# ---------------------------------------------------------------------------


class TestUnitConsistency:
    """Amplitude units must be consistent end-to-end."""

    def test_findings_amplitude_units_are_g(self) -> None:
        """All finding amplitude_metric.units must be 'g'."""
        sensors = _ALL_WHEEL_SENSORS
        samples: list[dict[str, Any]] = []
        for i in range(30):
            speed = 50.0 + i * 1.5
            whz = _wheel_hz(speed)
            for s in sensors:
                if s == "front-right":
                    peaks = [{"hz": whz, "amp": 0.08}]
                    vib_db = 28.0
                else:
                    peaks = [{"hz": 15.0, "amp": 0.005}]
                    vib_db = 10.0
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=speed,
                        client_name=s,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                    )
                )
        metadata = _standard_metadata()
        findings = build_findings_for_samples(metadata=metadata, samples=samples, lang="en")
        for f in findings:
            amp_metric = f.get("amplitude_metric")
            if isinstance(amp_metric, dict) and amp_metric.get("value") is not None:
                assert amp_metric.get("units") == "g", (
                    f"Expected 'g' units, got {amp_metric.get('units')}"
                )

    def test_evidence_metrics_include_strength_db(self) -> None:
        """Evidence metrics should include vibration_strength_db."""
        sensors = _ALL_WHEEL_SENSORS
        samples: list[dict[str, Any]] = []
        for i in range(30):
            speed = 50.0 + i * 1.5
            whz = _wheel_hz(speed)
            for s in sensors:
                if s == "front-right":
                    peaks = [{"hz": whz, "amp": 0.08}]
                    vib_db = 28.0
                else:
                    peaks = [{"hz": 15.0, "amp": 0.005}]
                    vib_db = 10.0
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=speed,
                        client_name=s,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                    )
                )
        metadata = _standard_metadata()
        findings = build_findings_for_samples(metadata=metadata, samples=samples, lang="en")
        for f in findings:
            ev = f.get("evidence_metrics")
            if isinstance(ev, dict) and "vibration_strength_db" in ev:
                db_val = ev["vibration_strength_db"]
                assert isinstance(db_val, (int, float)), "strength_db should be numeric"
                assert db_val >= 0, "strength_db should be non-negative"


# ---------------------------------------------------------------------------
# 7. Phase timeline tests
# ---------------------------------------------------------------------------


class TestPhaseTimeline:
    """Phase timeline should be present and reflect onset timing."""

    def test_timeline_present_in_summary(self) -> None:
        """summarize_run_data should include phase_timeline."""
        sensors = _ALL_WHEEL_SENSORS
        samples: list[dict[str, Any]] = []
        for i in range(20):
            speed = 0.0 if i < 5 else 40.0 + (i - 5) * 4
            for s in sensors:
                peaks = [{"hz": 10.0, "amp": 0.005}]
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=speed,
                        client_name=s,
                        top_peaks=peaks,
                        vibration_strength_db=10.0,
                    )
                )
        metadata = _standard_metadata()
        summary = summarize_run_data(metadata, samples, lang="en", file_name="timeline_test")
        assert "phase_timeline" in summary
        timeline = summary["phase_timeline"]
        assert isinstance(timeline, list)

    def test_timeline_entries_have_required_fields(self) -> None:
        """Each timeline entry should have phase, time, speed, and fault evidence fields."""
        sensors = _ALL_WHEEL_SENSORS
        samples: list[dict[str, Any]] = []
        for i in range(20):
            speed = 0.0 if i < 5 else 60.0
            for s in sensors:
                peaks = [{"hz": 10.0, "amp": 0.005}]
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=speed,
                        client_name=s,
                        top_peaks=peaks,
                        vibration_strength_db=10.0,
                    )
                )
        metadata = _standard_metadata()
        summary = summarize_run_data(metadata, samples, lang="en", file_name="timeline_fields")
        timeline = summary.get("phase_timeline", [])
        for entry in timeline:
            assert "phase" in entry
            assert "start_t_s" in entry
            assert "end_t_s" in entry
            assert "has_fault_evidence" in entry


# ---------------------------------------------------------------------------
# 8. Integration: phased scenario tests
# ---------------------------------------------------------------------------


class TestPhasedScenarios:
    """Phased scenarios should correctly identify fault onset and speed band."""

    def test_fault_only_at_high_speed(self) -> None:
        """Fault injected only at high speed should not be attributed to low-speed."""
        sensors = _ALL_WHEEL_SENSORS
        samples: list[dict[str, Any]] = []
        # Phase 1: road noise at low speed (0-15s)
        for i in range(15):
            speed = 30.0
            for s in sensors:
                peaks = [{"hz": 8.0, "amp": 0.005}]
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=speed,
                        client_name=s,
                        top_peaks=peaks,
                        vibration_strength_db=10.0,
                    )
                )
        # Phase 2: wheel fault at high speed (15-45s)
        for i in range(15, 45):
            speed = 100.0
            whz = _wheel_hz(speed)
            for s in sensors:
                if s == "front-right":
                    peaks = [{"hz": whz, "amp": 0.10}, {"hz": whz * 2, "amp": 0.04}]
                    vib_db = 30.0
                else:
                    peaks = [{"hz": 15.0, "amp": 0.005}]
                    vib_db = 10.0
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=speed,
                        client_name=s,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                    )
                )
        metadata = _standard_metadata()
        summary = summarize_run_data(metadata, samples, lang="en", file_name="high_speed_fault")
        top_causes = summary.get("top_causes", [])
        wheel_causes = [c for c in top_causes if str(c.get("source", "")) == "wheel/tire"]
        if wheel_causes:
            speed_band = str(wheel_causes[0].get("strongest_speed_band", ""))
            # Should reference high-speed range, not 30 km/h
            if speed_band:
                # Extract numbers from speed band
                import re

                nums = [int(x) for x in re.findall(r"\d+", speed_band)]
                if nums:
                    assert max(nums) >= 70, (
                        f"High-speed fault attributed to low speed band: {speed_band}"
                    )

    def test_cabin_sensor_not_fault_source_for_wheel(self) -> None:
        """Even if cabin sensor is strongest, wheel finding should point to wheel sensor."""
        sensors = _MIXED_SENSORS
        samples: list[dict[str, Any]] = []
        for i in range(30):
            speed = 60.0 + i * 1.5
            whz = _wheel_hz(speed)
            for s in sensors:
                if s == "driver-seat":
                    # Cabin sensor has strong transfer-path signal
                    peaks = [{"hz": whz, "amp": 0.09}, {"hz": whz * 2, "amp": 0.04}]
                    vib_db = 30.0
                elif s == "front-right":
                    # Wheel sensor has the fault (slightly weaker signal due to distance)
                    peaks = [{"hz": whz, "amp": 0.07}, {"hz": whz * 2, "amp": 0.03}]
                    vib_db = 27.0
                else:
                    peaks = [{"hz": 15.0, "amp": 0.005}]
                    vib_db = 10.0
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=speed,
                        client_name=s,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                    )
                )
        metadata = _standard_metadata()
        findings = build_findings_for_samples(metadata=metadata, samples=samples, lang="en")
        wheel_findings = [f for f in findings if str(f.get("finding_key", "")).startswith("wheel_")]
        for f in wheel_findings:
            strongest = str(f.get("strongest_location", ""))
            if strongest:
                assert is_wheel_location(strongest), (
                    f"Wheel finding assigned to non-wheel sensor: {strongest}"
                )
