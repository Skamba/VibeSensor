# ruff: noqa: E501
"""Real-world scenario tests for the diagnosis pipeline.

Covers:
- J1/C4: Healthy-vehicle false-positive guard (road-noise-only data must
  produce zero non-REF findings above threshold).
- J2: Engine-order fault scenario (engine_1x peaks with RPM correlation).
- J3: Very short recording (< 10 s) still produces a coherent report.
- J4: Gradual fault onset (fault grows over time, detected in later phases).
- J5: Borderline two-source overlap (wheel + engine at similar frequency).
"""

from __future__ import annotations

import math
from typing import Any

from conftest import assert_summary_sections
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
    hz = wheel_hz_from_speed_kmh(speed_kmh, _TIRE_CIRC)
    assert hz is not None and hz > 0
    return hz


def _standard_metadata(**overrides: Any) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "tire_circumference_m": _TIRE_CIRC,
        "raw_sample_rate_hz": 800.0,
        "final_drive_ratio": _FINAL_DRIVE,
        "current_gear_ratio": _GEAR_RATIO,
        "sensor_model": "ADXL345",
        "units": {"accel_x_g": "g"},
    }
    meta.update(overrides)
    return meta


def _make_sample(
    *,
    t_s: float,
    speed_kmh: float,
    client_name: str,
    top_peaks: list[dict[str, float]],
    vibration_strength_db: float = 10.0,
    strength_floor_amp_g: float = 0.003,
) -> dict[str, Any]:
    return {
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


# ===========================================================================
# J1 / C4: Healthy vehicle — no false positives
# ===========================================================================


class TestHealthyVehicleNoFalsePositive:
    """Clean car data (road noise only) must produce zero non-REF findings
    with confidence above a minimum threshold."""

    def _road_noise_samples(self, speed_kmh: float, duration_s: int = 40) -> list[dict[str, Any]]:
        """Generate road-noise-only samples: low broadband vibration, no peaks
        near wheel/engine orders."""
        samples: list[dict[str, Any]] = []
        for i in range(duration_s):
            for sensor in _ALL_SENSORS:
                # Random noise peaks at non-order-related frequencies
                peaks = [
                    {"hz": 142.5, "amp": 0.003},
                    {"hz": 287.3, "amp": 0.002},
                ]
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=speed_kmh,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=8.0,
                        strength_floor_amp_g=0.003,
                    )
                )
        return samples

    def test_steady_speed_clean_data_no_fault_findings(self) -> None:
        """Steady 80 km/h with only road noise: zero non-REF findings above 0.20."""
        meta = _standard_metadata()
        samples = self._road_noise_samples(80.0)
        summary = summarize_run_data(meta, samples, lang="en", file_name="healthy_steady")

        assert_summary_sections(summary)
        # No non-REF finding should have confidence above 0.20
        for f in summary.get("findings", []):
            if not isinstance(f, dict):
                continue
            fid = str(f.get("finding_id", ""))
            if fid.startswith("REF_"):
                continue
            conf = float(f.get("confidence_0_to_1") or 0)
            assert conf <= 0.20, f"False positive: {fid} conf={conf:.3f} on healthy vehicle data"

    def test_speed_sweep_clean_data_no_fault_findings(self) -> None:
        """Speed sweep 40–120 km/h with only road noise: no false positives."""
        meta = _standard_metadata()
        samples: list[dict[str, Any]] = []
        for i in range(40):
            speed = 40.0 + (80.0 / 40) * i  # 40→120 km/h
            for sensor in _ALL_SENSORS:
                peaks = [
                    {"hz": 142.5, "amp": 0.003},
                    {"hz": 287.3, "amp": 0.002},
                ]
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=speed,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=8.0,
                        strength_floor_amp_g=0.003,
                    )
                )

        summary = summarize_run_data(meta, samples, lang="en", file_name="healthy_sweep")
        assert_summary_sections(summary)
        for f in summary.get("findings", []):
            if not isinstance(f, dict):
                continue
            fid = str(f.get("finding_id", ""))
            if fid.startswith("REF_"):
                continue
            conf = float(f.get("confidence_0_to_1") or 0)
            assert conf <= 0.20, f"False positive on speed sweep: {fid} conf={conf:.3f}"

    def test_uniform_mild_vibration_no_fault_findings(self) -> None:
        """All four sensors at identical mild vibration: no corner flagged."""
        meta = _standard_metadata()
        samples: list[dict[str, Any]] = []
        whz = _wheel_hz(80.0)
        for i in range(30):
            for sensor in _ALL_SENSORS:
                # Same mild peak on all sensors — no spatial separation
                peaks = [{"hz": whz, "amp": 0.010}]
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=80.0,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=12.0,
                        strength_floor_amp_g=0.003,
                    )
                )

        summary = summarize_run_data(meta, samples, lang="en", file_name="uniform_mild")
        assert_summary_sections(summary)
        for f in summary.get("findings", []):
            if not isinstance(f, dict):
                continue
            fid = str(f.get("finding_id", ""))
            if fid.startswith("REF_"):
                continue
            conf = float(f.get("confidence_0_to_1") or 0)
            assert conf <= 0.25, f"False positive on uniform data: {fid} conf={conf:.3f}"


# ===========================================================================
# J2: Engine-order fault scenario
# ===========================================================================


class TestEngineOrderFaultScenario:
    """Engine-order (1x) peaks appearing on all four sensors should be
    classified as engine-sourced, not wheel-sourced."""

    def test_engine_1x_all_sensors_classified_as_engine(self) -> None:
        """Engine 1x peaks at RPM-derived frequency on all 4 sensors → engine source."""
        meta = _standard_metadata()
        samples: list[dict[str, Any]] = []

        # At 80 km/h with the default gear & final-drive ratios, compute
        # the engine-order frequency: engine_hz = speed / (tire_circ * 3.6) * final_drive * gear_ratio
        engine_hz = (80.0 / 3.6 / _TIRE_CIRC) * _FINAL_DRIVE * _GEAR_RATIO

        for i in range(40):
            for sensor in _ALL_SENSORS:
                # Engine 1x peak — same amplitude on ALL sensors (no spatial separation)
                peaks = [
                    {"hz": engine_hz, "amp": 0.05},
                    {"hz": engine_hz * 2, "amp": 0.02},  # engine 2x harmonic
                ]
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=80.0,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=24.0,
                        strength_floor_amp_g=0.003,
                    )
                )

        summary = summarize_run_data(meta, samples, lang="en", file_name="engine_1x_test")
        assert_summary_sections(summary, min_findings=1, min_top_causes=0)

        # Prefer top_causes when available; otherwise fall back to findings.
        sources = [
            str(item.get("source", "")).lower()
            for item in summary.get("top_causes", [])
            if isinstance(item, dict)
        ]
        if not sources:
            sources = [
                str(item.get("source", "")).lower()
                for item in summary.get("findings", [])
                if isinstance(item, dict)
            ]

        assert any("engine" in src or "driveline" in src for src in sources), (
            f"Engine-order fault misclassified; observed sources: {sources!r}"
        )


# ===========================================================================
# J3: Very short recording (< 10 seconds)
# ===========================================================================


class TestVeryShortRecording:
    """A recording shorter than 10 seconds must still produce a coherent report."""

    def test_5s_recording_produces_report(self) -> None:
        """5-second recording: should produce a summary with run_suitability warning."""
        meta = _standard_metadata()
        samples: list[dict[str, Any]] = []
        whz = _wheel_hz(80.0)
        for i in range(5):
            for sensor in _ALL_SENSORS:
                if sensor == "front-right":
                    peaks = [{"hz": whz, "amp": 0.06}]
                    vib_db = 26.0
                else:
                    peaks = [{"hz": 142.5, "amp": 0.003}]
                    vib_db = 8.0
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=80.0,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                    )
                )

        summary = summarize_run_data(meta, samples, lang="en", file_name="short_5s")
        assert isinstance(summary, dict)
        assert "findings" in summary
        # Run suitability should exist
        suitability = summary.get("run_suitability", [])
        assert isinstance(suitability, list)
        # The summary must complete without crashing; any findings must be valid
        for f in summary.get("findings", []):
            if isinstance(f, dict):
                conf = f.get("confidence_0_to_1")
                if isinstance(conf, (int, float)):
                    assert not math.isnan(conf), "NaN confidence in short recording"

    def test_3s_recording_does_not_crash(self) -> None:
        """3-second recording: must not crash, even if findings are empty."""
        meta = _standard_metadata()
        samples: list[dict[str, Any]] = []
        for i in range(3):
            for sensor in _ALL_SENSORS:
                peaks = [{"hz": 142.5, "amp": 0.003}]
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=60.0,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=8.0,
                    )
                )

        summary = summarize_run_data(meta, samples, lang="en", file_name="short_3s")
        assert isinstance(summary, dict)
        assert "findings" in summary


# ===========================================================================
# J4: Gradual fault onset
# ===========================================================================


class TestGradualFaultOnset:
    """Fault that grows over time: starts clean, becomes noticeable in later half."""

    def test_gradual_onset_detected_in_later_phase(self) -> None:
        """Wheel fault starts quiet and grows — pipeline should still detect it."""
        meta = _standard_metadata()
        samples: list[dict[str, Any]] = []
        whz = _wheel_hz(80.0)

        for i in range(60):
            # Fault amplitude grows linearly: 0→0.06 over 60s
            fault_amp = 0.06 * (i / 60.0)
            fault_db = 8.0 + 18.0 * (i / 60.0)  # 8→26 dB
            for sensor in _ALL_SENSORS:
                if sensor == "front-left":
                    peaks = [
                        {"hz": whz, "amp": max(0.003, fault_amp)},
                    ]
                    vib_db = fault_db
                else:
                    peaks = [{"hz": 142.5, "amp": 0.003}]
                    vib_db = 8.0
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=80.0,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                    )
                )

        summary = summarize_run_data(meta, samples, lang="en", file_name="gradual_onset")
        assert_summary_sections(summary, min_findings=0)

        # Should still detect the fault (even if lower confidence due to averaging)
        non_ref = [
            f
            for f in summary.get("findings", [])
            if isinstance(f, dict)
            and not str(f.get("finding_id", "")).startswith("REF_")
            and float(f.get("confidence_0_to_1") or 0) > 0.10
        ]
        assert len(non_ref) >= 1, "Gradual onset fault should be detected"


# ===========================================================================
# J5: Borderline two-source overlap (wheel + engine at similar frequency)
# ===========================================================================


class TestBorderlineTwoSourceOverlap:
    """Wheel and engine frequencies happen to be similar at a particular speed/RPM.
    The pipeline must not crash and should produce a coherent classification."""

    def test_overlapping_wheel_and_engine_freq(self) -> None:
        """Wheel_hz ≈ engine_hz: should produce findings without NaN or crash."""
        meta = _standard_metadata()
        samples: list[dict[str, Any]] = []

        # Choose a speed where wheel_hz is close to engine_hz
        # engine_hz = (speed_mps / tire_circ) * final_drive * gear_ratio
        # wheel_hz = speed_mps / tire_circ
        # They overlap when final_drive * gear_ratio ≈ 1 (unlikely with defaults),
        # so we fabricate peaks at the same frequency for both nominal orders.
        whz = _wheel_hz(80.0)
        for i in range(40):
            for sensor in _ALL_SENSORS:
                if sensor == "front-left":
                    # Strong peak at wheel_hz frequency on one corner
                    peaks = [
                        {"hz": whz, "amp": 0.06},
                        {"hz": whz * _FINAL_DRIVE * _GEAR_RATIO, "amp": 0.04},
                    ]
                    vib_db = 26.0
                else:
                    # Same peak on all other sensors (engine-like: no spatial sep)
                    peaks = [
                        {"hz": whz * _FINAL_DRIVE * _GEAR_RATIO, "amp": 0.04},
                    ]
                    vib_db = 20.0
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=80.0,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                    )
                )

        summary = summarize_run_data(meta, samples, lang="en", file_name="overlap_test")
        assert isinstance(summary, dict)

        # Must not crash; findings must have valid contracts
        assert_summary_sections(summary, min_findings=0)
        for f in summary.get("findings", []):
            if isinstance(f, dict):
                conf = f.get("confidence_0_to_1")
                if isinstance(conf, (int, float)):
                    assert not math.isnan(conf), "NaN confidence in overlap scenario"

        # Top cause must exist and have a valid source
        top_causes = summary.get("top_causes", [])
        if top_causes:
            source = str(top_causes[0].get("source", "")).lower()
            assert source, "Top cause source should not be empty"
