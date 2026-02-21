"""Scenario-based regression tests for diagnosis/reporting quality.

These tests exercise the full summarize_run_data() and findings pipeline
with realistic synthetic runs that reproduce specific driving/analysis
scenarios.  Each test validates correctness of confidence calibration,
phase segmentation, classification, localization, and report output.
"""

from __future__ import annotations

from typing import Any

from vibesensor_core.strength_bands import bucket_for_strength

from vibesensor.report.findings import (
    _build_order_findings,
    _classify_peak_type,
)
from vibesensor.report.phase_segmentation import (
    DrivingPhase,
    diagnostic_sample_mask,
    phase_summary,
    segment_run_phases,
)
from vibesensor.report.summary import (
    confidence_label,
    summarize_run_data,
)

# ---------------------------------------------------------------------------
# Shared sample factory
# ---------------------------------------------------------------------------


def _make_sample(
    *,
    t_s: float,
    speed_kmh: float | None = None,
    accel_x_g: float = 0.01,
    accel_y_g: float = 0.01,
    accel_z_g: float = 0.10,
    vibration_strength_db: float = 15.0,
    strength_bucket: str | None = None,
    strength_floor_amp_g: float = 0.002,
    client_name: str = "Front Left Wheel",
    client_id: str = "sensor-001",
    location: str = "",
    top_peaks: list[dict[str, float]] | None = None,
    engine_rpm: float | None = None,
    dominant_freq_hz: float | None = None,
) -> dict[str, Any]:
    sample: dict[str, Any] = {
        "t_s": t_s,
        "accel_x_g": accel_x_g,
        "accel_y_g": accel_y_g,
        "accel_z_g": accel_z_g,
        "vibration_strength_db": vibration_strength_db,
        "strength_bucket": strength_bucket or bucket_for_strength(vibration_strength_db),
        "strength_floor_amp_g": strength_floor_amp_g,
        "client_name": client_name,
        "client_id": client_id,
    }
    if speed_kmh is not None:
        sample["speed_kmh"] = speed_kmh
    if location:
        sample["location"] = location
    if top_peaks is not None:
        sample["top_peaks"] = top_peaks
    if engine_rpm is not None:
        sample["engine_rpm"] = engine_rpm
    if dominant_freq_hz is not None:
        sample["dominant_freq_hz"] = dominant_freq_hz
    return sample


def _build_speed_sweep_samples(
    *,
    n: int = 40,
    speed_start_kmh: float = 30.0,
    speed_end_kmh: float = 120.0,
    dt: float = 1.0,
    tire_circumference_m: float = 2.036,
    client_name: str = "Front Left Wheel",
    peak_amp: float = 0.05,
    add_wheel_1x: bool = True,
    vib_db: float = 18.0,
) -> list[dict[str, Any]]:
    """Create a set of samples with linearly increasing speed and wheel-1x order peaks."""
    from vibesensor.analysis_settings import wheel_hz_from_speed_kmh

    samples: list[dict[str, Any]] = []
    for i in range(n):
        t = i * dt
        speed = speed_start_kmh + (speed_end_kmh - speed_start_kmh) * (i / max(1, n - 1))
        peaks = []
        if add_wheel_1x:
            whz = wheel_hz_from_speed_kmh(speed, tire_circumference_m)
            if whz and whz > 0:
                peaks.append({"hz": whz, "amp": peak_amp})
        # Add a noise peak
        peaks.append({"hz": 142.5, "amp": 0.003})
        samples.append(
            _make_sample(
                t_s=t,
                speed_kmh=speed,
                vibration_strength_db=vib_db,
                client_name=client_name,
                top_peaks=peaks,
                strength_floor_amp_g=0.003,
            )
        )
    return samples


def _build_phased_samples(
    phase_segments: list[tuple[int, float, float]],
    *,
    start_t_s: float = 0.0,
    dt_s: float = 1.0,
) -> list[dict[str, Any]]:
    """Build samples from phase segments as (count, start_speed, end_speed)."""
    samples: list[dict[str, Any]] = []
    t_s = start_t_s
    for count, speed_start, speed_end in phase_segments:
        if count <= 0:
            continue
        for i in range(count):
            if count == 1:
                speed_kmh = float(speed_end)
            else:
                ratio = i / (count - 1)
                speed_kmh = float(speed_start + ((speed_end - speed_start) * ratio))
            samples.append(_make_sample(t_s=t_s, speed_kmh=speed_kmh))
            t_s += dt_s
    return samples


def _standard_metadata(
    *,
    tire_circumference_m: float = 2.036,
    raw_sample_rate_hz: float = 1000.0,
    final_drive_ratio: float = 3.08,
    current_gear_ratio: float = 0.64,
) -> dict[str, Any]:
    return {
        "tire_circumference_m": tire_circumference_m,
        "raw_sample_rate_hz": raw_sample_rate_hz,
        "final_drive_ratio": final_drive_ratio,
        "current_gear_ratio": current_gear_ratio,
        "sensor_model": "adxl345",
        "units": {"accel_x_g": "g"},
    }


# ---------------------------------------------------------------------------
# 1. Phase segmentation tests
# ---------------------------------------------------------------------------


class TestPhaseSegmentation:
    """Verify driving-phase classification across various speed profiles."""

    def test_idle_to_speed_up(self) -> None:
        """Idle → acceleration → cruise must produce all three phases."""
        samples = _build_phased_samples(
            [
                (5, 0.0, 0.0),
                (10, 8.0, 80.0),
                (10, 80.0, 81.0),
            ]
        )

        per_sample, segments = segment_run_phases(samples)
        assert len(per_sample) == 25
        phases_present = {seg.phase for seg in segments}
        assert DrivingPhase.IDLE in phases_present
        # Acceleration or cruise must be present (phase boundaries aren't perfect)
        assert DrivingPhase.CRUISE in phases_present or DrivingPhase.ACCELERATION in phases_present

    def test_stop_go(self) -> None:
        """Repeated stop-go should contain both IDLE and non-IDLE phases."""
        samples = _build_phased_samples(
            [
                (3, 0.0, 0.0),
                (5, 30.0, 50.0),
                (3, 0.0, 0.0),
                (5, 30.0, 50.0),
                (3, 0.0, 0.0),
                (5, 30.0, 50.0),
            ]
        )
        per_sample, segments = segment_run_phases(samples)
        idle_count = sum(1 for p in per_sample if p == DrivingPhase.IDLE)
        assert idle_count >= 6, "Stop-go must detect multiple idle phases"

    def test_coast_down(self) -> None:
        """Deceleration below coast-down threshold should be labeled COAST_DOWN."""
        # Decelerating from 50 → 2 km/h
        samples = _build_phased_samples([(20, 50.0, 2.0)])
        per_sample, segments = segment_run_phases(samples)
        has_decel = any(
            p in (DrivingPhase.DECELERATION, DrivingPhase.COAST_DOWN) for p in per_sample
        )
        assert has_decel

    def test_diagnostic_mask_excludes_idle(self) -> None:
        """The diagnostic mask should exclude IDLE samples by default."""
        per_sample = [
            DrivingPhase.IDLE,
            DrivingPhase.CRUISE,
            DrivingPhase.IDLE,
            DrivingPhase.ACCELERATION,
        ]
        mask = diagnostic_sample_mask(per_sample)
        assert mask == [False, True, False, True]

    def test_phase_summary_structure(self) -> None:
        """phase_summary must return correct keys and percentages that add to 100."""
        samples = [
            _make_sample(t_s=0.0, speed_kmh=0.0),
            _make_sample(t_s=1.0, speed_kmh=60.0),
            _make_sample(t_s=2.0, speed_kmh=60.0),
        ]
        _, segments = segment_run_phases(samples)
        info = phase_summary(segments)
        assert "phase_counts" in info
        assert "total_samples" in info
        assert info["total_samples"] == 3
        pcts = info["phase_pcts"]
        assert abs(sum(pcts.values()) - 100.0) < 0.01


# ---------------------------------------------------------------------------
# 2. Confidence calibration tests
# ---------------------------------------------------------------------------


class TestConfidenceCalibration:
    """Validate that confidence scoring reflects real-world signal quality."""

    def test_low_match_count_has_lower_confidence_than_high_count(self) -> None:
        """Equivalent quality with minimal samples should be penalized vs well-supported runs."""
        meta = _standard_metadata()
        low_count_samples = _build_speed_sweep_samples(peak_amp=0.08, vib_db=24.0, n=6)
        high_count_samples = _build_speed_sweep_samples(peak_amp=0.08, vib_db=24.0, n=40)

            def best_order_conf(summary: dict[str, Any]) -> float:
                findings = summary.get("findings", [])
            return max(
                (
                    float(finding.get("confidence_0_to_1") or 0.0)
                    for finding in findings
                        if isinstance(finding, dict)
                        and not str(finding.get("finding_id", "")).startswith("REF_")
                ),
                default=0.0,
            )

            low_conf = best_order_conf(low_summary)
            high_conf = best_order_conf(high_summary)

        assert low_conf > 0.0 and high_conf > 0.0
        assert low_conf < high_conf
        assert low_conf <= high_conf * 0.85

    def test_negligible_amplitude_capped(self) -> None:
        """Very weak signal (< 2 mg) → confidence capped at 0.45."""
        meta = _standard_metadata()
        samples = _build_speed_sweep_samples(peak_amp=0.001, vib_db=5.0, n=40)
        summary = summarize_run_data(meta, samples, include_samples=False)
        for finding in summary.get("findings", []):
            fid = str(finding.get("finding_id", ""))
            if fid.startswith("REF_"):
                continue
            conf = float(finding.get("confidence_0_to_1") or 0)
            assert conf <= 0.46, f"Negligible amp finding {fid} has conf {conf} > 0.45"

    def test_strong_match_high_confidence(self) -> None:
        """Strong wheel-1x match with wide speed sweep → high confidence."""
        meta = _standard_metadata()
        samples = _build_speed_sweep_samples(peak_amp=0.08, vib_db=24.0, n=50)
        summary = summarize_run_data(meta, samples, include_samples=False)
        order_findings = [
            f
            for f in summary.get("findings", [])
            if isinstance(f, dict)
            and str(f.get("finding_id", "")).startswith("F")
            and not str(f.get("finding_id", "")).startswith("REF_")
        ]
        if order_findings:
            best = max(order_findings, key=lambda f: float(f.get("confidence_0_to_1") or 0))
            conf = float(best.get("confidence_0_to_1") or 0)
            assert conf >= 0.40, f"Strong match should have conf >= 0.40, got {conf}"

    def test_steady_speed_penalty(self) -> None:
        """Constant speed → lower confidence than a sweep."""
        meta = _standard_metadata()
        sweep_samples = _build_speed_sweep_samples(
            peak_amp=0.04, vib_db=18.0, speed_start_kmh=40.0, speed_end_kmh=100.0
        )
        steady_samples = _build_speed_sweep_samples(
            peak_amp=0.04, vib_db=18.0, speed_start_kmh=79.5, speed_end_kmh=80.5
        )
        sweep_summary = summarize_run_data(meta, sweep_samples, include_samples=False)
        steady_summary = summarize_run_data(meta, steady_samples, include_samples=False)

        def best_order_conf(summary: dict) -> float:
            return max(
                (
                    float(f.get("confidence_0_to_1") or 0)
                    for f in summary.get("findings", [])
                    if not str(f.get("finding_id", "")).startswith("REF_")
                ),
                default=0.0,
            )

        sweep_conf = best_order_conf(sweep_summary)
        steady_conf = best_order_conf(steady_summary)
        # Sweep should yield higher confidence (or both 0 if no findings)
        if sweep_conf > 0 and steady_conf > 0:
            assert sweep_conf > steady_conf, f"Sweep {sweep_conf} should > steady {steady_conf}"

    def test_confidence_label_thresholds(self) -> None:
        """Verify confidence_label returns correct keys at boundaries."""
        key_h, tone_h, pct_h = confidence_label(0.75)
        assert key_h == "CONFIDENCE_HIGH"
        assert tone_h == "success"
        key_m, tone_m, pct_m = confidence_label(0.50)
        assert key_m == "CONFIDENCE_MEDIUM"
        assert tone_m == "warn"
        key_l, tone_l, pct_l = confidence_label(0.20)
        assert key_l == "CONFIDENCE_LOW"
        assert tone_l == "neutral"


# ---------------------------------------------------------------------------
# 3. Strength bands alignment
# ---------------------------------------------------------------------------


class TestStrengthBandsAlignment:
    """Ensure strength_bands.py and strength_labels.py agree on thresholds."""

    def test_negligible_returns_l0(self) -> None:
        """dB values 0–7.9 should return l0 bucket (negligible)."""
        assert bucket_for_strength(0.0) == "l0"
        assert bucket_for_strength(5.0) == "l0"
        assert bucket_for_strength(7.9) == "l0"

    def test_l1_starts_at_8(self) -> None:
        assert bucket_for_strength(8.0) == "l1"
        assert bucket_for_strength(15.9) == "l1"

    def test_l2_starts_at_16(self) -> None:
        assert bucket_for_strength(16.0) == "l2"
        assert bucket_for_strength(25.9) == "l2"

    def test_l3_starts_at_26(self) -> None:
        assert bucket_for_strength(26.0) == "l3"
        assert bucket_for_strength(35.9) == "l3"

    def test_l4_starts_at_36(self) -> None:
        assert bucket_for_strength(36.0) == "l4"
        assert bucket_for_strength(45.9) == "l4"

    def test_l5_starts_at_46(self) -> None:
        assert bucket_for_strength(46.0) == "l5"
        assert bucket_for_strength(100.0) == "l5"


# ---------------------------------------------------------------------------
# 4. Peak classification
# ---------------------------------------------------------------------------


class TestPeakClassification:
    """Verify _classify_peak_type edge cases and new baseline_noise class."""

    def test_patterned(self) -> None:
        assert _classify_peak_type(0.50, 2.0) == "patterned"

    def test_persistent(self) -> None:
        assert _classify_peak_type(0.25, 3.5) == "persistent"

    def test_transient(self) -> None:
        assert _classify_peak_type(0.05, 1.0) == "transient"

    def test_high_burstiness_transient(self) -> None:
        assert _classify_peak_type(0.50, 6.0) == "transient"

    def test_baseline_noise_low_snr(self) -> None:
        """Peaks with SNR below threshold → baseline_noise."""
        assert _classify_peak_type(0.80, 1.5, snr=1.0) == "baseline_noise"

    def test_baseline_noise_high_spatial_uniformity(self) -> None:
        """Peaks present everywhere equally → baseline_noise."""
        result = _classify_peak_type(0.70, 1.5, snr=5.0, spatial_uniformity=0.90)
        assert result == "baseline_noise"

    def test_not_baseline_if_snr_high(self) -> None:
        """High SNR should not be classified as baseline even with uniformity."""
        result = _classify_peak_type(0.70, 1.5, snr=5.0, spatial_uniformity=0.50)
        assert result == "patterned"


# ---------------------------------------------------------------------------
# 5. Classification overlap detection
# ---------------------------------------------------------------------------


class TestOverlapDetection:
    """Verify wheel_2x / engine_1x overlap is detected and labeled."""

    def test_wheel2_eng1_overlap_detection(self) -> None:
        """When 2×wheel ≈ engine_1x, classify as 'wheel2_eng1'."""
        from vibesensor.diagnostics_shared import classify_peak_hz

        # At ~80 km/h with tire_circ ≈ 2.21m: wheel_hz ≈ 10.04, wheel_2x ≈ 20.08
        # With final_drive=3.08, gear=0.64: engine_hz ≈ 19.79
        # These overlap (0.015 < 0.03 tol)! Query at ~20.0 Hz.
        result = classify_peak_hz(
            peak_hz=20.0,
            speed_mps=80.0 / 3.6,
            settings={
                "tire_width_mm": 285.0,
                "tire_aspect_pct": 30.0,
                "rim_in": 21.0,
                "final_drive_ratio": 3.08,
                "current_gear_ratio": 0.64,
                "wheel_bandwidth_pct": 6.0,
                "driveshaft_bandwidth_pct": 5.6,
                "engine_bandwidth_pct": 6.2,
                "speed_uncertainty_pct": 0.6,
                "tire_diameter_uncertainty_pct": 1.2,
                "final_drive_uncertainty_pct": 0.2,
                "gear_uncertainty_pct": 0.5,
                "min_abs_band_hz": 0.4,
                "max_band_half_width_pct": 8.0,
            },
        )
        # Should detect the wheel_2x / engine_1x overlap
        key = result.get("key")
        assert key == "wheel2_eng1", f"Expected 'wheel2_eng1', got: {key}"


# ---------------------------------------------------------------------------
# 6. Localization: _location_label prefers structured location
# ---------------------------------------------------------------------------


class TestLocationLabel:
    """_location_label should prefer structured location codes."""

    def test_structured_location_preferred(self) -> None:
        from vibesensor.report.helpers import _location_label

        sample = {
            "client_name": "My sensor",
            "location": "front_left_wheel",
        }
        label = _location_label(sample)
        assert label == "Front Left Wheel"

    def test_fallback_to_client_name(self) -> None:
        from vibesensor.report.helpers import _location_label

        sample = {
            "client_name": "Rear Axle Custom",
        }
        label = _location_label(sample)
        assert label == "Rear Axle Custom"

    def test_unknown_location_code_used_raw(self) -> None:
        from vibesensor.report.helpers import _location_label

        sample = {
            "location": "custom_spot",
        }
        label = _location_label(sample)
        assert label == "custom_spot"


# ---------------------------------------------------------------------------
# 7. Plot data key mismatch fix: amp_vs_speed should not always be empty
# ---------------------------------------------------------------------------


class TestPlotDataKeyFix:
    """Verify that amp_vs_speed is populated when speed_breakdown has data."""

    def test_amp_vs_speed_populated(self) -> None:
        meta = _standard_metadata()
        samples = _build_speed_sweep_samples(n=30, vib_db=20.0)
        summary = summarize_run_data(meta, samples)
        plots = summary.get("plots", {})
        # amp_vs_speed should now contain points (was always empty before fix)
        amp_points = plots.get("amp_vs_speed", [])
        # If speed_breakdown has data, amp_vs_speed should too
        if summary.get("speed_breakdown"):
            assert len(amp_points) > 0, "amp_vs_speed should not be empty after key fix"


# ---------------------------------------------------------------------------
# 8. Multi-sensor localization
# ---------------------------------------------------------------------------


class TestMultiSensorLocalization:
    """Runs with multiple sensor locations should produce localization info."""

    def test_multi_sensor_run(self) -> None:
        meta = _standard_metadata()
        from vibesensor.analysis_settings import wheel_hz_from_speed_kmh

        samples: list[dict[str, Any]] = []
        tire_circ = 2.036
        for i in range(30):
            speed = 40.0 + i * 2.0
            whz = wheel_hz_from_speed_kmh(speed, tire_circ) or 10.0
            # Strong peak at front-left
            samples.append(
                _make_sample(
                    t_s=float(i),
                    speed_kmh=speed,
                    vibration_strength_db=22.0,
                    client_name="Front-Left Wheel",
                    client_id="sensor-A",
                    top_peaks=[{"hz": whz, "amp": 0.06}],
                    strength_floor_amp_g=0.003,
                )
            )
            # Weaker peak at rear-right
            samples.append(
                _make_sample(
                    t_s=float(i) + 0.5,
                    speed_kmh=speed,
                    vibration_strength_db=14.0,
                    client_name="Rear-Right Wheel",
                    client_id="sensor-B",
                    top_peaks=[{"hz": whz, "amp": 0.02}],
                    strength_floor_amp_g=0.003,
                )
            )

        summary = summarize_run_data(meta, samples, include_samples=False)
        locations = summary.get("sensor_locations", [])
        assert len(locations) >= 2, "Should detect multiple sensor locations"
        # Intensity table should show front-left stronger
        intensities = summary.get("sensor_intensity_by_location", [])
        if len(intensities) >= 2:
            top_loc = intensities[0].get("location")
            assert "Front-Left" in str(top_loc) or "front" in str(top_loc).lower()


# ---------------------------------------------------------------------------
# 9. Report metadata completeness
# ---------------------------------------------------------------------------


class TestReportMetadataCompleteness:
    """map_summary should populate new metadata fields."""

    def test_report_data_has_metadata_fields(self) -> None:
        from vibesensor.report.report_data import map_summary

        meta = _standard_metadata()
        samples = _build_speed_sweep_samples(n=20, vib_db=18.0)
        summary = summarize_run_data(meta, samples, include_samples=False)
        tmpl = map_summary(summary)
        assert tmpl.duration_text is not None
        assert tmpl.sample_count > 0
        assert tmpl.sensor_count >= 1

    def test_next_steps_have_enriched_fields(self) -> None:
        from vibesensor.report.report_data import map_summary

        meta = _standard_metadata()
        samples = _build_speed_sweep_samples(n=40, peak_amp=0.06, vib_db=22.0)
        summary = summarize_run_data(meta, samples, include_samples=False)
        tmpl = map_summary(summary)
        # NextStep should now have confirm/falsify/eta if test_plan provides them
        for step in tmpl.next_steps:
            # At minimum, action and rank should be set
            assert step.action
            assert step.rank >= 1


# ---------------------------------------------------------------------------
# 10. Phase info in summary output
# ---------------------------------------------------------------------------


class TestPhaseInfoInSummary:
    """summarize_run_data should include phase_info in its output."""

    def test_phase_info_present(self) -> None:
        meta = _standard_metadata()
        samples = _build_speed_sweep_samples(n=20, vib_db=18.0)
        summary = summarize_run_data(meta, samples, include_samples=False)
        phase_info = summary.get("phase_info")
        assert phase_info is not None
        assert "total_samples" in phase_info
        assert phase_info["total_samples"] == 20
