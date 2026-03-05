# ruff: noqa: E501
"""Phased-scenario diagnosis tests – speed-scaled order tracking and localization.

Root causes addressed:
1. Simulator generates tones at FIXED Hz (100 km/h reference) but analysis expects
   Hz that SCALE with speed → order matches fail at speed ≠ 100 km/h.
2. Corner localization drifts when non-fault sensors leak similar amplitude at
   accidental frequency alignments.
3. Speed-band attribution picks wrong band when matched points cluster at
   accidental-match speeds rather than fault-onset speeds.
4. Wheel vs engine/driveline gating fails when fixed-frequency tones accidentally
   match engine/driveshaft orders at certain speeds.
5. Confidence is inflated on weak/ambiguous localization.

These tests construct synthetic JSONL-style samples with SPEED-SCALED order
peaks (the correct behavior) and verify the analysis pipeline produces the
expected corner, system, speed window, and confidence.
"""

from __future__ import annotations

from typing import Any

import pytest
from builders import (
    make_fault_samples as _make_fault_samples,
)
from builders import (
    make_sample as _make_sample,
)
from builders import (
    make_speed_sweep_fault_samples as _make_speed_sweep_fault_samples,
)
from builders import (
    standard_metadata as _standard_metadata,
)
from builders import (
    wheel_hz as _wheel_hz,
)

from vibesensor.analysis.findings import _classify_peak_type
from vibesensor.analysis.summary import summarize_run_data

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _build_fault_samples_at_speed(
    *,
    speed_kmh: float,
    fault_sensor: str,
    other_sensors: list[str],
    n_samples: int = 30,
    dt_s: float = 1.0,
    start_t_s: float = 0.0,
    fault_amp: float = 0.06,
    noise_amp: float = 0.004,
    fault_vib_db: float = 24.0,
    noise_vib_db: float = 8.0,
    add_wheel_2x: bool = True,
    transfer_fraction: float = 0.20,
) -> list[dict[str, Any]]:
    """Generate fixed-speed wheel-order fault samples using shared builders."""
    assert fault_sensor not in other_sensors, "fault_sensor must not be listed in other_sensors"
    sensors = [fault_sensor, *other_sensors]
    return _make_fault_samples(
        fault_sensor=fault_sensor,
        sensors=sensors,
        speed_kmh=speed_kmh,
        n_samples=n_samples,
        dt_s=dt_s,
        start_t_s=start_t_s,
        fault_amp=fault_amp,
        noise_amp=noise_amp,
        fault_vib_db=fault_vib_db,
        noise_vib_db=noise_vib_db,
        add_wheel_2x=add_wheel_2x,
        transfer_fraction=transfer_fraction,
    )


def _build_speed_sweep_fault_samples(
    *,
    speed_start_kmh: float,
    speed_end_kmh: float,
    fault_sensor: str,
    other_sensors: list[str],
    n_samples: int = 40,
    dt_s: float = 1.0,
    start_t_s: float = 0.0,
    fault_amp: float = 0.06,
    noise_amp: float = 0.004,
    fault_vib_db: float = 24.0,
    noise_vib_db: float = 8.0,
    transfer_fraction: float = 0.20,
) -> list[dict[str, Any]]:
    """Generate linear speed-sweep fault samples using shared builders."""
    assert fault_sensor not in other_sensors, "fault_sensor must not be listed in other_sensors"
    sensors = [fault_sensor, *other_sensors]
    return _make_speed_sweep_fault_samples(
        fault_sensor=fault_sensor,
        sensors=sensors,
        speed_start=speed_start_kmh,
        speed_end=speed_end_kmh,
        n_steps=n_samples,
        samples_per_step=1,
        dt_s=dt_s,
        start_t_s=start_t_s,
        fault_amp=fault_amp,
        noise_amp=noise_amp,
        fault_vib_db=fault_vib_db,
        noise_vib_db=noise_vib_db,
    )


def _extract_top_finding(summary: dict[str, Any]) -> dict[str, Any] | None:
    """Get the highest-confidence non-reference finding from a summary."""
    findings = summary.get("findings", [])
    non_ref = [
        f
        for f in findings
        if isinstance(f, dict) and not str(f.get("finding_id", "")).startswith("REF_")
    ]
    if not non_ref:
        return None
    return max(non_ref, key=lambda f: float(f.get("confidence_0_to_1") or 0))


def _assert_finding_location(
    summary: dict[str, Any],
    expected: str,
    label: str = "",
) -> dict[str, Any]:
    """Assert that the top finding's strongest_location contains *expected*.

    Returns the top finding for further assertions.
    """
    top = _extract_top_finding(summary)
    assert top is not None, f"{label}: Should produce at least one diagnostic finding"
    location = str(top.get("strongest_location") or "").lower()
    assert expected in location, (
        f"{label}: Expected '{expected}', got '{top.get('strongest_location')}'"
    )
    return top


def _assert_finding_source(
    summary: dict[str, Any],
    expected_sources: tuple[str, ...] = ("wheel", "tire"),
    label: str = "",
) -> dict[str, Any]:
    """Assert that the top finding's suspected_source contains one of *expected_sources*.

    Returns the top finding for further assertions.
    """
    top = _extract_top_finding(summary)
    assert top is not None, f"{label}: Should produce a finding"
    source = str(top.get("suspected_source") or "").lower()
    assert any(s in source for s in expected_sources), (
        f"{label}: Expected one of {expected_sources}, got '{top.get('suspected_source')}'"
    )
    return top


def _parse_speed_band(finding: dict[str, Any]) -> tuple[float, float]:
    """Parse strongest_speed_band into (low, high) floats.  Returns (0, 0) on failure."""
    speed_band = str(finding.get("strongest_speed_band") or "")
    parts = speed_band.replace("km/h", "").strip().split("-")
    try:
        low = float(parts[0].strip())
        high = float(parts[-1].strip()) if len(parts) > 1 else low
    except (ValueError, IndexError):
        low = high = 0.0
    return low, high


# ---------------------------------------------------------------------------
# Scenario 1: Idle→100 km/h, fault appears only at sustained 100 km/h
# Expected: front-right wheel fault at ~100 km/h
# ---------------------------------------------------------------------------


class TestScenario1IdleToSpeedUp:
    """Scenario: Vehicle starts from idle, ramps to 100, fault appears at 100 km/h."""

    def test_correct_corner_identified(self) -> None:
        """The front-right sensor should be identified as the fault location."""
        meta = _standard_metadata()
        # Phase A: idle (no fault)
        idle_samples: list[dict[str, Any]] = []
        for i in range(10):
            for sensor in ["front-left", "front-right", "rear-left", "rear-right"]:
                idle_samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=0.0,
                        client_name=sensor,
                        top_peaks=[{"hz": 13.0, "amp": 0.003}],
                        vibration_strength_db=5.0,
                    )
                )
        # Phase B: ramp 20→100 (short, no fault yet)
        ramp_samples = _build_speed_sweep_fault_samples(
            speed_start_kmh=20.0,
            speed_end_kmh=100.0,
            fault_sensor="front-right",
            other_sensors=["front-left", "rear-left", "rear-right"],
            n_samples=8,
            dt_s=2.0,
            start_t_s=10.0,
            fault_amp=0.015,  # Mild during ramp
            fault_vib_db=14.0,
        )
        # Phase C: sustained 100 km/h with clear fault
        fault_samples = _build_fault_samples_at_speed(
            speed_kmh=100.0,
            fault_sensor="front-right",
            other_sensors=["front-left", "rear-left", "rear-right"],
            n_samples=40,
            dt_s=1.0,
            start_t_s=26.0,
            fault_amp=0.06,
            fault_vib_db=24.0,
        )
        all_samples = idle_samples + ramp_samples + fault_samples
        summary = summarize_run_data(meta, all_samples, include_samples=False)
        _assert_finding_location(summary, "front-right", "Scenario 1")

    def test_correct_system_identified(self) -> None:
        """The suspected source should be wheel/tire."""
        meta = _standard_metadata()
        samples = _build_fault_samples_at_speed(
            speed_kmh=100.0,
            fault_sensor="front-right",
            other_sensors=["front-left", "rear-left", "rear-right"],
            n_samples=40,
            fault_amp=0.06,
            fault_vib_db=24.0,
        )
        summary = summarize_run_data(meta, samples, include_samples=False)
        _assert_finding_source(summary, label="Scenario 1")

    def test_correct_speed_band(self) -> None:
        """The speed band should include 100 km/h (90-100 or 100-110)."""
        meta = _standard_metadata()
        samples = _build_fault_samples_at_speed(
            speed_kmh=100.0,
            fault_sensor="front-right",
            other_sensors=["front-left", "rear-left", "rear-right"],
            n_samples=40,
            fault_amp=0.06,
            fault_vib_db=24.0,
        )
        summary = summarize_run_data(meta, samples, include_samples=False)
        top = _extract_top_finding(summary)
        assert top is not None
        band_low, band_high = _parse_speed_band(top)
        speed_band = top.get("strongest_speed_band", "")
        assert band_low >= 80.0 and band_high <= 130.0, (
            f"Scenario 1: Speed band should cover ~100 km/h, got '{speed_band}'"
        )


# ---------------------------------------------------------------------------
# Scenario 2: Stop-go city drive, intermittent rear-left at 50/60 km/h
# Expected: rear-left wheel fault at 50-60 km/h
# ---------------------------------------------------------------------------


class TestScenario2StopGoIntermittent:
    """Scenario: Stop-go with rear-left fault appearing at 50-60 km/h."""

    def test_correct_corner_rear_left(self) -> None:
        """Rear-left should be identified, not engine or rear-right."""
        meta = _standard_metadata()
        samples: list[dict[str, Any]] = []
        t = 0.0
        sensors = ["front-left", "front-right", "rear-left", "rear-right"]

        # Phase A: idle
        for _ in range(8):
            for s in sensors:
                samples.append(
                    _make_sample(
                        t_s=t,
                        speed_kmh=0.0,
                        client_name=s,
                        top_peaks=[{"hz": 13.0, "amp": 0.003}],
                        vibration_strength_db=5.0,
                    )
                )
            t += 1.0

        # Phase B: drive at 30 km/h (no fault)
        for _ in range(10):
            for s in sensors:
                samples.append(
                    _make_sample(
                        t_s=t,
                        speed_kmh=30.0,
                        client_name=s,
                        top_peaks=[{"hz": 87.3, "amp": 0.004}],
                        vibration_strength_db=8.0,
                    )
                )
            t += 1.0

        # Phase C: drive at 50 km/h with rear-left fault
        fault_c = _build_fault_samples_at_speed(
            speed_kmh=50.0,
            fault_sensor="rear-left",
            other_sensors=["front-left", "front-right", "rear-right"],
            n_samples=15,
            start_t_s=t,
            fault_amp=0.05,
            fault_vib_db=22.0,
        )
        samples.extend(fault_c)
        t += 15.0

        # Phase D: slow down to 10 (no fault)
        for _ in range(8):
            for s in sensors:
                samples.append(
                    _make_sample(
                        t_s=t,
                        speed_kmh=10.0,
                        client_name=s,
                        top_peaks=[{"hz": 87.3, "amp": 0.003}],
                        vibration_strength_db=6.0,
                    )
                )
            t += 1.0

        # Phase E: drive at 60 km/h with rear-left fault again
        fault_e = _build_fault_samples_at_speed(
            speed_kmh=60.0,
            fault_sensor="rear-left",
            other_sensors=["front-left", "front-right", "rear-right"],
            n_samples=20,
            start_t_s=t,
            fault_amp=0.055,
            fault_vib_db=23.0,
        )
        samples.extend(fault_e)

        summary = summarize_run_data(meta, samples, include_samples=False)
        _assert_finding_location(summary, "rear-left", "Scenario 2")

    def test_system_is_wheel_not_engine(self) -> None:
        """Source should be wheel/tire, not engine (common misclassification)."""
        meta = _standard_metadata()
        samples = _build_fault_samples_at_speed(
            speed_kmh=55.0,
            fault_sensor="rear-left",
            other_sensors=["front-left", "front-right", "rear-right"],
            n_samples=30,
            fault_amp=0.05,
            fault_vib_db=22.0,
        )
        summary = summarize_run_data(meta, samples, include_samples=False)
        _assert_finding_source(summary, label="Scenario 2")

    def test_speed_band_covers_50_60(self) -> None:
        """Speed band should be around 50-60 km/h, not 30-40."""
        meta = _standard_metadata()
        # Fault at both 50 and 60 km/h
        samples_50 = _build_fault_samples_at_speed(
            speed_kmh=50.0,
            fault_sensor="rear-left",
            other_sensors=["front-left", "front-right", "rear-right"],
            n_samples=20,
            start_t_s=0.0,
            fault_amp=0.05,
            fault_vib_db=22.0,
        )
        samples_60 = _build_fault_samples_at_speed(
            speed_kmh=60.0,
            fault_sensor="rear-left",
            other_sensors=["front-left", "front-right", "rear-right"],
            n_samples=20,
            start_t_s=20.0,
            fault_amp=0.055,
            fault_vib_db=23.0,
        )
        summary = summarize_run_data(meta, samples_50 + samples_60, include_samples=False)
        top = _extract_top_finding(summary)
        assert top is not None
        speed_band = str(top.get("strongest_speed_band") or "")
        # Should contain 50 or 60, not 30 or 40
        band_low = 0
        for part in speed_band.replace("km/h", "").split("-"):
            try:
                band_low = int(part.strip())
                break
            except ValueError:
                continue
        assert band_low >= 40, (
            f"Scenario 2: Speed band should be >= 40 km/h range, got '{speed_band}'"
        )


# ---------------------------------------------------------------------------
# Scenario 3: Highway, rear-right fault at 120 km/h only
# Expected: rear-right wheel at ~120 km/h
# ---------------------------------------------------------------------------


class TestScenario3HighwayRearRight:
    """Scenario: Highway cruise, rear-right fault strongest at 120 km/h."""

    def test_correct_corner_rear_right(self) -> None:
        """Rear-right should be identified at 120 km/h."""
        meta = _standard_metadata()
        # Phase A: 60 km/h baseline (no fault)
        baseline_60 = _build_fault_samples_at_speed(
            speed_kmh=60.0,
            fault_sensor="rear-right",
            other_sensors=["front-left", "front-right", "rear-left"],
            n_samples=10,
            start_t_s=0.0,
            fault_amp=0.004,
            noise_amp=0.003,  # No real fault at 60
            fault_vib_db=8.0,
            noise_vib_db=7.0,
        )
        # Phase B: 90 km/h baseline (no fault)
        baseline_90 = _build_fault_samples_at_speed(
            speed_kmh=90.0,
            fault_sensor="rear-right",
            other_sensors=["front-left", "front-right", "rear-left"],
            n_samples=10,
            start_t_s=10.0,
            fault_amp=0.004,
            noise_amp=0.003,
            fault_vib_db=8.0,
            noise_vib_db=7.0,
        )
        # Phase C: 120 km/h with clear fault
        fault_120 = _build_fault_samples_at_speed(
            speed_kmh=120.0,
            fault_sensor="rear-right",
            other_sensors=["front-left", "front-right", "rear-left"],
            n_samples=30,
            start_t_s=20.0,
            fault_amp=0.07,
            fault_vib_db=26.0,
        )
        # Phase D: back to 100 (no fault)
        baseline_100 = _build_fault_samples_at_speed(
            speed_kmh=100.0,
            fault_sensor="rear-right",
            other_sensors=["front-left", "front-right", "rear-left"],
            n_samples=10,
            start_t_s=50.0,
            fault_amp=0.004,
            noise_amp=0.003,
            fault_vib_db=8.0,
            noise_vib_db=7.0,
        )
        all_samples = baseline_60 + baseline_90 + fault_120 + baseline_100
        summary = summarize_run_data(meta, all_samples, include_samples=False)
        _assert_finding_location(summary, "rear-right", "Scenario 3")

    def test_speed_band_covers_120(self) -> None:
        """Speed band should be 110-120 or 120-130 km/h range."""
        meta = _standard_metadata()
        fault_120 = _build_fault_samples_at_speed(
            speed_kmh=120.0,
            fault_sensor="rear-right",
            other_sensors=["front-left", "front-right", "rear-left"],
            n_samples=35,
            fault_amp=0.07,
            fault_vib_db=26.0,
        )
        summary = summarize_run_data(meta, fault_120, include_samples=False)
        top = _extract_top_finding(summary)
        assert top is not None
        band_low, band_high = _parse_speed_band(top)
        speed_band = top.get("strongest_speed_band", "")
        assert band_low >= 100.0 and band_high <= 140.0, (
            f"Scenario 3: Speed band should cover ~120 km/h, got '{speed_band}'"
        )


# ---------------------------------------------------------------------------
# Scenario 4: Coast-down, front-left strongest at mid-range (70-90 km/h)
# ---------------------------------------------------------------------------


class TestScenario4CoastDownMidRange:
    """Scenario: Coast-down with front-left fault strongest at 70-90 km/h."""

    @staticmethod
    def _build_coast_down_samples(
        *,
        add_harmonic: bool = True,
    ) -> list[dict[str, Any]]:
        """Generate a 110→30 km/h coast-down with front-left fault peaking at 70-90 km/h."""
        samples: list[dict[str, Any]] = []
        t = 0.0
        for i in range(50):
            speed = 110.0 - i * 1.6  # 110→30 km/h
            whz = _wheel_hz(speed)
            mid_strength = max(0.0, 1.0 - abs(speed - 80.0) / 40.0)
            fault_amp = 0.01 + 0.06 * mid_strength
            fault_vib_db = 10.0 + 16.0 * mid_strength

            fault_peaks: list[dict[str, float]] = [{"hz": whz, "amp": fault_amp}]
            if add_harmonic:
                fault_peaks.append({"hz": whz * 2, "amp": fault_amp * 0.3})
            fault_peaks.append({"hz": 142.5, "amp": 0.003})
            samples.append(
                _make_sample(
                    t_s=t,
                    speed_kmh=speed,
                    client_name="front-left",
                    top_peaks=fault_peaks,
                    vibration_strength_db=fault_vib_db,
                    strength_floor_amp_g=0.003,
                )
            )
            for other in ["front-right", "rear-left", "rear-right"]:
                samples.append(
                    _make_sample(
                        t_s=t,
                        speed_kmh=speed,
                        client_name=other,
                        top_peaks=[{"hz": 142.5, "amp": 0.003}, {"hz": 87.3, "amp": 0.003}],
                        vibration_strength_db=8.0,
                        strength_floor_amp_g=0.003,
                    )
                )
            t += 1.0
        return samples

    def test_correct_corner_front_left(self) -> None:
        """Front-left should be identified."""
        meta = _standard_metadata()
        samples = self._build_coast_down_samples(add_harmonic=True)
        summary = summarize_run_data(meta, samples, include_samples=False)
        _assert_finding_location(summary, "front-left", "Scenario 4")

    def test_speed_band_emphasizes_midrange(self) -> None:
        """Speed band should emphasize mid-range (70-90) not extremes."""
        meta = _standard_metadata()
        samples = self._build_coast_down_samples(add_harmonic=False)
        summary = summarize_run_data(meta, samples, include_samples=False)
        top = _extract_top_finding(summary)
        assert top is not None
        speed_band = str(top.get("strongest_speed_band") or "")
        # Should contain 70, 80, or 90 in the band label
        assert any(str(s) in speed_band for s in [70, 80, 90]), (
            f"Scenario 4: Speed band should be mid-range (70-90), got '{speed_band}'"
        )


# ---------------------------------------------------------------------------
# Scenario 5: Mixed noise then clear fault at 100 km/h
# ---------------------------------------------------------------------------


class TestScenario5MixedNoiseThenFault:
    """Scenario: Road noise phases then clear front-left fault at 100 km/h."""

    def test_correct_corner_front_left(self) -> None:
        meta = _standard_metadata()
        # Phase A: 80 km/h road noise (no distinct fault)
        noise_samples: list[dict[str, Any]] = []
        for i in range(25):
            for s in ["front-left", "front-right", "rear-left", "rear-right"]:
                noise_samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=80.0,
                        client_name=s,
                        top_peaks=[{"hz": 87.3, "amp": 0.005}, {"hz": 142.5, "amp": 0.004}],
                        vibration_strength_db=10.0,
                        strength_floor_amp_g=0.004,
                    )
                )
        # Phase C: 100 km/h with clear front-left fault
        fault = _build_fault_samples_at_speed(
            speed_kmh=100.0,
            fault_sensor="front-left",
            other_sensors=["front-right", "rear-left", "rear-right"],
            n_samples=35,
            start_t_s=25.0,
            fault_amp=0.06,
            fault_vib_db=24.0,
        )
        summary = summarize_run_data(meta, noise_samples + fault, include_samples=False)
        _assert_finding_location(summary, "front-left", "Scenario 5")


# ---------------------------------------------------------------------------
# Unit tests: speed-band attribution accuracy
# ---------------------------------------------------------------------------


class TestSpeedBandAttribution:
    """Verify speed-band attribution uses matched-point speeds, not global."""

    def test_speed_band_matches_fault_speed_not_overall(self) -> None:
        """When fault is only at 120 km/h in a 60→120→100 run, band should be ~120."""
        meta = _standard_metadata()
        baseline = _build_fault_samples_at_speed(
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
        fault = _build_fault_samples_at_speed(
            speed_kmh=120.0,
            fault_sensor="front-right",
            other_sensors=["front-left", "rear-left", "rear-right"],
            n_samples=30,
            start_t_s=15.0,
            fault_amp=0.07,
            fault_vib_db=26.0,
        )
        cool = _build_fault_samples_at_speed(
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
        summary = summarize_run_data(meta, baseline + fault + cool, include_samples=False)
        top = _extract_top_finding(summary)
        assert top is not None
        speed_band = str(top.get("strongest_speed_band") or "")
        assert "120" in speed_band or "110" in speed_band, (
            f"Speed band should reflect 120 km/h fault, got '{speed_band}'"
        )


# ---------------------------------------------------------------------------
# Unit tests: wheel vs engine/driveline gating
# ---------------------------------------------------------------------------


class TestWheelVsEngineDrivelineGating:
    """Verify that wheel-order faults aren't misclassified as engine/driveline."""

    def test_wheel_1x_not_misclassified_as_engine(self) -> None:
        """A clear wheel_1x-only pattern should never produce engine as top source."""
        meta = _standard_metadata()
        # Wide speed sweep so wheel_1x varies and isn't confused with engine
        samples = _build_speed_sweep_fault_samples(
            speed_start_kmh=40.0,
            speed_end_kmh=120.0,
            fault_sensor="front-right",
            other_sensors=["front-left", "rear-left", "rear-right"],
            n_samples=50,
            fault_amp=0.06,
            fault_vib_db=24.0,
        )
        summary = summarize_run_data(meta, samples, include_samples=False)
        top = _extract_top_finding(summary)
        assert top is not None
        source = str(top.get("suspected_source") or "").lower()
        assert "engine" not in source, (
            f"Wheel-only fault should not be classified as engine, got '{source}'"
        )

    def test_constant_speed_wheel_not_engine(self) -> None:
        """At constant speed, wheel_1x could overlap engine_1x. Wheel should still win."""
        meta = _standard_metadata()
        samples = _build_fault_samples_at_speed(
            speed_kmh=80.0,
            fault_sensor="rear-left",
            other_sensors=["front-left", "front-right", "rear-right"],
            n_samples=40,
            fault_amp=0.05,
            fault_vib_db=22.0,
        )
        summary = summarize_run_data(meta, samples, include_samples=False)
        findings = [
            f
            for f in summary.get("findings", [])
            if isinstance(f, dict) and not str(f.get("finding_id", "")).startswith("REF_")
        ]
        if findings:
            top = max(findings, key=lambda f: float(f.get("confidence_0_to_1") or 0))
            source = str(top.get("suspected_source") or "").lower()
            # Should be wheel/tire, not engine
            assert "wheel" in source or "tire" in source or "unknown" in source, (
                f"Constant-speed wheel fault should not be engine, got '{source}'"
            )


# ---------------------------------------------------------------------------
# Unit tests: confidence calibration with spatial ambiguity
# ---------------------------------------------------------------------------


class TestConfidenceWithSpatialAmbiguity:
    """Verify confidence is properly reduced when localization is weak."""

    def test_equal_amplitude_all_sensors_low_confidence(self) -> None:
        """When all sensors show the same fault pattern, confidence should be capped."""
        meta = _standard_metadata()
        samples: list[dict[str, Any]] = []
        for i in range(30):
            speed = 60.0 + i * 1.0
            whz = _wheel_hz(speed)
            for s in ["front-left", "front-right", "rear-left", "rear-right"]:
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=speed,
                        client_name=s,
                        top_peaks=[
                            {"hz": whz, "amp": 0.05},
                            {"hz": whz * 2, "amp": 0.02},
                            {"hz": 142.5, "amp": 0.003},
                        ],
                        vibration_strength_db=22.0,
                        strength_floor_amp_g=0.003,
                    )
                )
        summary = summarize_run_data(meta, samples, include_samples=False)
        top = _extract_top_finding(summary)
        assert top is not None, "Equal-amplitude all-sensor scenario must produce a finding"
        conf = float(top.get("confidence_0_to_1") or 0)
        # With all sensors showing equal amplitude, spatial confidence should be weak
        assert conf < 0.70, f"Equal-amplitude all sensors should have conf < 0.70, got {conf:.2f}"

    def test_single_sensor_dominant_higher_confidence(self) -> None:
        """One dominant sensor with 10x amplitude should get higher confidence."""
        meta = _standard_metadata()
        samples = _build_speed_sweep_fault_samples(
            speed_start_kmh=50.0,
            speed_end_kmh=110.0,
            fault_sensor="front-right",
            other_sensors=["front-left", "rear-left", "rear-right"],
            n_samples=40,
            fault_amp=0.08,
            noise_amp=0.003,
            fault_vib_db=26.0,
            noise_vib_db=6.0,
        )
        summary = summarize_run_data(meta, samples, include_samples=False)
        top = _extract_top_finding(summary)
        assert top is not None
        conf = float(top.get("confidence_0_to_1") or 0)
        assert conf >= 0.40, f"Dominant single sensor should have conf >= 0.40, got {conf:.2f}"


# ---------------------------------------------------------------------------
# Unit tests: transient de-weighting
# ---------------------------------------------------------------------------


class TestTransientDeWeighting:
    """Verify that brief transient peaks don't get promoted above persistent faults."""

    def test_transient_classified_correctly(self) -> None:
        """A peak with < 15% presence should be classified as transient."""
        assert _classify_peak_type(0.10, 8.0) == "transient"
        assert _classify_peak_type(0.05, 2.0) == "transient"

    def test_patterned_classified_correctly(self) -> None:
        """A peak with >= 40% presence and low burstiness should be patterned."""
        assert _classify_peak_type(0.50, 2.0) == "patterned"
        assert _classify_peak_type(0.80, 1.5) == "patterned"

    def test_baseline_noise_classified(self) -> None:
        """Low SNR → baseline noise."""
        assert _classify_peak_type(0.60, 1.5, snr=1.0) == "baseline_noise"


# ---------------------------------------------------------------------------
# Integration test: multi-sensor localization stability
# ---------------------------------------------------------------------------


class TestLocalizationStability:
    """Verify left/right discrimination doesn't flip under slight amplitude changes."""

    _ALL_SENSORS = ["front-left", "front-right", "rear-left", "rear-right"]

    @pytest.mark.parametrize("fault_sensor", _ALL_SENSORS)
    def test_localization_stable_with_clear_dominance(self, fault_sensor: str) -> None:
        """Each sensor should be correctly identified when amp ratio is >= 3x."""
        meta = _standard_metadata()
        others = [s for s in self._ALL_SENSORS if s != fault_sensor]
        samples = _build_speed_sweep_fault_samples(
            speed_start_kmh=50.0,
            speed_end_kmh=100.0,
            fault_sensor=fault_sensor,
            other_sensors=others,
            n_samples=40,
            fault_amp=0.06,
            noise_amp=0.003,
            fault_vib_db=24.0,
            noise_vib_db=6.0,
        )
        summary = summarize_run_data(meta, samples, include_samples=False)
        _assert_finding_location(summary, fault_sensor, f"Localization({fault_sensor})")
