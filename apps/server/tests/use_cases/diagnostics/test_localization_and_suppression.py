"""Source-aware localization, unit consistency, and phased scenario contracts."""

from __future__ import annotations

from typing import Any

import pytest
from test_support import make_sample as _make_sample
from test_support import make_speed_sweep_fault_samples as _make_speed_sweep_fault_samples
from test_support import standard_metadata as _standard_metadata
from test_support import wheel_hz as _wheel_hz

from vibesensor.adapters.analysis_summary import build_findings_for_samples, summarize_run_data
from vibesensor.domain import OrderMatchObservation
from vibesensor.shared.locations import is_wheel_location
from vibesensor.use_cases.diagnostics.location_analysis import summarize_order_match_locations

# ---------------------------------------------------------------------------
# Helpers (reused from test_scenario_ground_truth patterns)
# ---------------------------------------------------------------------------


_ALL_WHEEL_SENSORS = ["front-left", "front-right", "rear-left", "rear-right"]
_MIXED_SENSORS = ["front-left", "front-right", "rear-left", "rear-right", "driver-seat", "trunk"]


def _build_fault_samples(
    sensors: list[str],
    fault_sensor: str,
    n_samples: int = 30,
) -> list[dict[str, Any]]:
    """Build a speed-sweep wheel fault using shared test builders."""
    return _make_speed_sweep_fault_samples(
        fault_sensor=fault_sensor,
        sensors=sensors,
        speed_start=50.0,
        speed_end=50.0 + ((n_samples - 1) * 1.5),
        n_steps=n_samples,
        samples_per_step=1,
        fault_amp=0.08,
        noise_amp=0.005,
        fault_vib_db=28.0,
        noise_vib_db=10.0,
    )


def _wheel_findings(
    findings: tuple | list,
    *,
    exclude_ref: bool = False,
) -> list:
    """Return findings whose *finding_key* starts with ``wheel_``."""
    return [
        f
        for f in findings
        if (not exclude_ref or not f.finding_id.startswith("REF_"))
        and f.finding_key.startswith("wheel_")
    ]


def _wheel_causes(top_causes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return causes whose *source* is ``wheel/tire``."""
    return [c for c in top_causes if str(c.get("source", "")) == "wheel/tire"]


# ---------------------------------------------------------------------------
# 1. Source-aware localization tests
# ---------------------------------------------------------------------------


class TestSourceAwareLocalization:
    """Wheel diagnoses must prioritize wheel/corner sensors as fault sources."""

    def test_wheel_diagnosis_prefers_wheel_sensor_over_cabin(self) -> None:
        """When cabin sensor has higher amplitude but wheel sensors are present,
        wheel sensor should be selected as fault source for wheel/tire diagnoses.
        """
        matches = []
        for i in range(20):
            speed = 60.0 + i * 2
            whz = _wheel_hz(speed)
            # Cabin sensor: stronger signal
            matches.append(
                OrderMatchObservation(
                    predicted_hz=whz,
                    matched_hz=whz,
                    rel_error=0.02,
                    amp=0.08,
                    location="Driver Seat",
                    speed_kmh=speed,
                ),
            )
            # Wheel sensor: slightly weaker but valid
            matches.append(
                OrderMatchObservation(
                    predicted_hz=whz,
                    matched_hz=whz,
                    rel_error=0.01,
                    amp=0.06,
                    location="Front Left",
                    speed_kmh=speed,
                ),
            )

        _, hotspot = summarize_order_match_locations(
            matches,
            lang="en",
            suspected_source="wheel/tire",
        )
        assert hotspot is not None
        top_location = hotspot.top_location
        assert is_wheel_location(top_location), (
            f"Wheel diagnosis assigned to non-wheel sensor: {top_location}"
        )

    def test_non_wheel_source_allows_any_location(self) -> None:
        """For non-wheel diagnoses (e.g., engine), any sensor can be fault source."""
        matches = []
        for i in range(20):
            speed = 60.0 + i * 2
            matches.append(
                OrderMatchObservation(
                    predicted_hz=25.0,
                    matched_hz=25.0,
                    rel_error=0.02,
                    amp=0.08,
                    location="Engine Bay",
                    speed_kmh=speed,
                ),
            )
            matches.append(
                OrderMatchObservation(
                    predicted_hz=25.0,
                    matched_hz=25.0,
                    rel_error=0.03,
                    amp=0.04,
                    location="Front Left",
                    speed_kmh=speed,
                ),
            )

        _, hotspot = summarize_order_match_locations(
            matches,
            lang="en",
            suspected_source="engine",
        )
        assert hotspot is not None
        top_location = hotspot.top_location
        assert top_location == "Engine Bay"

    def test_no_wheel_sensors_falls_back_to_strongest(self) -> None:
        """If only cabin/chassis sensors are present, use strongest available."""
        matches = []
        for i in range(15):
            speed = 50.0 + i * 3
            whz = _wheel_hz(speed)
            matches.append(
                OrderMatchObservation(
                    predicted_hz=whz,
                    matched_hz=whz,
                    rel_error=0.02,
                    amp=0.07,
                    location="Driver Seat",
                    speed_kmh=speed,
                ),
            )
            matches.append(
                OrderMatchObservation(
                    predicted_hz=whz,
                    matched_hz=whz,
                    rel_error=0.03,
                    amp=0.03,
                    location="Trunk",
                    speed_kmh=speed,
                ),
            )

        _, hotspot = summarize_order_match_locations(
            matches,
            lang="en",
            suspected_source="wheel/tire",
        )
        assert hotspot is not None
        # No wheel sensors available, so it should fall back to strongest
        top_location = hotspot.top_location
        assert top_location == "Driver Seat"


# 2. Unit consistency tests
# ---------------------------------------------------------------------------


class TestUnitConsistency:
    """Amplitude units must be consistent end-to-end."""

    @pytest.fixture
    def fault_findings(self) -> tuple:
        """Shared findings from a single-sensor (front-right) fault scenario."""
        samples = _build_fault_samples(_ALL_WHEEL_SENSORS, "front-right")
        metadata = _standard_metadata()
        return build_findings_for_samples(metadata=metadata, samples=samples, lang="en")

    def test_findings_amplitude_units_are_db(self, fault_findings: tuple) -> None:
        """All finding vibration_strength_db must be present when non-None."""
        for f in fault_findings:
            if f.vibration_strength_db is not None:
                assert isinstance(f.vibration_strength_db, float)

    def test_evidence_metrics_include_strength_db(
        self,
        fault_findings: tuple,
    ) -> None:
        """Evidence should include vibration_strength_db."""
        for f in fault_findings:
            if f.evidence is not None and f.evidence.vibration_strength_db is not None:
                db_val = f.evidence.vibration_strength_db
                assert isinstance(db_val, (int, float)), "strength_db should be numeric"
                assert db_val >= 0, "strength_db should be non-negative"


# ---------------------------------------------------------------------------
# 3. Phase timeline tests
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
                    ),
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
                    ),
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
# 4. Integration: phased scenario tests
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
                    ),
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
                    ),
                )
        metadata = _standard_metadata()
        summary = summarize_run_data(metadata, samples, lang="en", file_name="high_speed_fault")
        wc = _wheel_causes(summary.get("top_causes", []))
        if wc:
            speed_band = str(wc[0].get("strongest_speed_band", ""))
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
                    ),
                )
        metadata = _standard_metadata()
        findings = build_findings_for_samples(metadata=metadata, samples=samples, lang="en")
        for f in _wheel_findings(findings):
            strongest = f.strongest_location or ""
            if strongest:
                assert is_wheel_location(strongest), (
                    f"Wheel finding assigned to non-wheel sensor: {strongest}"
                )
