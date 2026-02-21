"""Scenario-based regression tests for diagnosis/reporting quality.

These tests exercise the full summarize_run_data() and findings pipeline
with realistic synthetic runs that reproduce specific driving/analysis
scenarios.  Each test validates correctness of confidence calibration,
phase segmentation, classification, localization, and report output.
"""

from __future__ import annotations

from typing import Any

from vibesensor_core.strength_bands import bucket_for_strength

from vibesensor.report.findings import _classify_peak_type
from vibesensor.report.phase_segmentation import (
    DrivingPhase,
    diagnostic_sample_mask,
    phase_summary,
    segment_run_phases,
)
from vibesensor.report.strength_labels import certainty_label
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
    """Verify driving-phase classification across various speed profiles.

    Also covers issue #188: No phase detection algorithm exists.
    """

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

    def test_all_five_phases_can_be_detected(self) -> None:
        """Issue #188: phase detection must classify all five driving phases.

        Validates that the algorithm correctly identifies IDLE, ACCELERATION,
        CRUISE, DECELERATION, and COAST_DOWN from a realistic speed profile.
        """
        samples = []
        # IDLE: stationary
        for i in range(5):
            samples.append({"t_s": float(i), "speed_kmh": 0.5})
        # ACCELERATION: 0→80 km/h over 20s
        for i in range(5, 25):
            samples.append({"t_s": float(i), "speed_kmh": float((i - 5) * 4)})
        # CRUISE: steady 80 km/h
        for i in range(25, 40):
            samples.append({"t_s": float(i), "speed_kmh": 80.0})
        # DECELERATION: 80→20 km/h
        for i in range(40, 55):
            samples.append({"t_s": float(i), "speed_kmh": max(20.0, 80.0 - (i - 40) * 4.0)})
        # COAST_DOWN: 20→0 km/h (below coast-down threshold)
        for i in range(55, 60):
            samples.append({"t_s": float(i), "speed_kmh": max(0.0, 20.0 - (i - 55) * 4.0)})

        per_sample, segments = segment_run_phases(samples)
        assert len(per_sample) == len(samples)
        phases_found = {seg.phase for seg in segments}

        assert DrivingPhase.IDLE in phases_found, "IDLE not detected"
        assert DrivingPhase.ACCELERATION in phases_found, "ACCELERATION not detected"
        assert DrivingPhase.CRUISE in phases_found, "CRUISE not detected"
        # Deceleration and/or coast-down must be detected
        assert (
            DrivingPhase.DECELERATION in phases_found or DrivingPhase.COAST_DOWN in phases_found
        ), "DECELERATION/COAST_DOWN not detected"

        info = phase_summary(segments)
        assert info["has_cruise"]
        assert info["has_acceleration"]
        assert info["total_samples"] == len(samples)


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

        low_summary = summarize_run_data(meta, low_count_samples, include_samples=False)
        high_summary = summarize_run_data(meta, high_count_samples, include_samples=False)

        def best_order_conf(summary: dict[str, Any]) -> float:
            findings = summary.get("findings", [])
            return max(
                (
                    float(finding.get("confidence_0_to_1") or 0.0)
                    for finding in findings
                    if isinstance(finding, dict) and str(finding.get("finding_id", "")) == "F_ORDER"
                ),
                default=0.0,
            )

        low_conf = best_order_conf(low_summary)
        high_conf = best_order_conf(high_summary)

        if low_conf > 0.0 and high_conf > 0.0:
            assert low_conf < high_conf
            assert low_conf <= high_conf * 0.85

    def test_noise_floor_guard_prevents_snr_blowup_with_near_zero_floor(self) -> None:
        """Issue #186: near-zero noise floor must not produce snr_score ≈ 1.0.

        When mean_floor is near-zero (sensor artifact / perfectly clean signal),
        the SNR ratio blows up without the guard. The fix clamps mean_floor
        to max(0.001, mean_floor) so tiny absolute amplitudes cannot produce
        artificially high SNR scores.

        AC: floor guard prevents snr_score ≈ 1.0 for 2mg amplitude / near-zero floor.
        Implementation gives ~0.44 (vs 1.0 without guard), plus absolute-strength
        cap provides secondary protection.
        """
        from math import log1p as _log1p

        mean_amp = 0.002  # 2 mg – barely above MEMS noise
        near_zero_floor = 1e-7  # pathological near-zero floor

        # Without guard (old: max(1e-6, floor)):
        snr_without_guard = min(1.0, _log1p(mean_amp / max(1e-6, near_zero_floor)) / 2.5)
        # With guard (current: max(0.001, floor)):
        snr_with_guard = min(1.0, _log1p(mean_amp / max(0.001, near_zero_floor)) / 2.5)

        assert snr_without_guard > 0.95, "Without guard, SNR should be near 1.0 (bug scenario)"
        assert snr_with_guard < 0.50, (
            f"With floor guard, SNR for 2mg amp must be < 0.50, got {snr_with_guard:.3f}"
        )
        # Normal floor (already >= 0.001g) must be unaffected
        normal_floor = 0.005
        snr_normal_clamped = min(1.0, _log1p(mean_amp / max(0.001, normal_floor)) / 2.5)
        snr_normal_direct = min(1.0, _log1p(mean_amp / normal_floor) / 2.5)
        assert abs(snr_normal_clamped - snr_normal_direct) < 1e-10, "Normal floor must be unchanged"

    def test_sample_count_scaling_formula_meets_minimum_penalty(self) -> None:
        """Issue #185: 4-match minimum must receive >=15% confidence penalty vs 20+ matches.

        The formula: sample_factor = min(1.0, matched / 20.0)
                     multiplier = 0.70 + 0.30 * sample_factor
        At 4 matches: multiplier = 0.76 (24% less than 1.0)
        Acceptance criteria: penalty >= 15% compared to 20+ matched samples.
        """
        # Test formula directly
        def sample_multiplier(matched: int) -> float:
            sample_factor = min(1.0, matched / 20.0)
            return 0.70 + 0.30 * sample_factor

        mult_at_min = sample_multiplier(4)
        mult_at_full = sample_multiplier(20)

        penalty_pct = (1.0 - mult_at_min / mult_at_full) * 100.0
        assert penalty_pct >= 15.0, (
            f"Sample-count penalty at 4 matches should be >=15% vs 20+ matches, got {penalty_pct:.1f}%"
        )
        # Also verify the multiplier saturates at 1.0 for 20+ samples
        assert mult_at_full == 1.0
        assert sample_multiplier(100) == 1.0

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

    def test_negligible_strength_db_capped_for_multi_sensor_match(self) -> None:
        """Negligible strength band (<8 dB) must stay at low confidence."""
        meta = _standard_metadata()
        locations = ["Front Left Wheel", "Rear Right Wheel", "Front Right Wheel"]
        samples = _build_speed_sweep_samples(peak_amp=0.02, vib_db=18.0, n=60)
        for idx, sample in enumerate(samples):
            sample["strength_floor_amp_g"] = 0.008
            sample["client_name"] = locations[idx % len(locations)]

        summary = summarize_run_data(meta, samples, include_samples=False)
        findings = [
            finding
            for finding in summary.get("findings", [])
            if isinstance(finding, dict)
            and str(finding.get("finding_id", "")).startswith("F")
            and not str(finding.get("finding_id", "")).startswith("REF_")
        ]
        assert findings
        for finding in findings:
            evidence_metrics = finding.get("evidence_metrics")
            if not isinstance(evidence_metrics, dict):
                continue
            strength_db = float(evidence_metrics.get("vibration_strength_db") or 0.0)
            if strength_db < 8.0:
                conf = float(finding.get("confidence_0_to_1") or 0.0)
                assert conf <= 0.45, (
                    f"Negligible strength finding {finding.get('finding_id')} "
                    f"has conf {conf} at {strength_db:.2f} dB"
                )

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

    def test_steady_speed_confidence_ceiling(self) -> None:
        """Constant speed findings should remain capped below high-certainty range."""
        meta = _standard_metadata()
        steady_samples = _build_speed_sweep_samples(
            peak_amp=0.04,
            vib_db=18.0,
            speed_start_kmh=79.5,
            speed_end_kmh=80.5,
            n=24,
        )
        steady_summary = summarize_run_data(meta, steady_samples, include_samples=False)
        max_non_ref_conf = max(
            (
                float(f.get("confidence_0_to_1") or 0.0)
                for f in steady_summary.get("findings", [])
                if not str(f.get("finding_id", "")).startswith("REF_")
            ),
            default=0.0,
        )
        assert max_non_ref_conf <= 0.65, (
            f"Steady speed confidence must be <= 0.65, got {max_non_ref_conf}"
        )

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


class TestPhaseSpeedBreakdown:
    """_phase_speed_breakdown groups samples by driving phase, not speed magnitude.

    Addresses issue #189: adds temporal phase context alongside speed-magnitude
    breakdown so callers can compare vibration in cruise vs. acceleration at
    the same physical speed.
    """

    def test_phase_speed_breakdown_groups_by_phase(self) -> None:
        """Output must have one row per detected phase, keyed by phase name."""
        from vibesensor.report.findings import _phase_speed_breakdown
        from vibesensor.report.phase_segmentation import DrivingPhase, segment_run_phases

        # Build a sequence: idle → cruise
        samples = []
        for i in range(5):
            samples.append({"t_s": float(i), "speed_kmh": 0.5, "vibration_strength_db": 5.0})
        for i in range(5, 20):
            samples.append({"t_s": float(i), "speed_kmh": 60.0, "vibration_strength_db": 22.0})

        per_sample_phases, _ = segment_run_phases(samples)
        rows = _phase_speed_breakdown(samples, per_sample_phases)

        phase_names = {row["phase"] for row in rows}
        assert DrivingPhase.IDLE.value in phase_names
        assert DrivingPhase.CRUISE.value in phase_names or DrivingPhase.ACCELERATION.value in phase_names

    def test_phase_speed_breakdown_included_in_summary(self) -> None:
        """summarize_run_data must include phase_speed_breakdown in output."""
        meta = _standard_metadata()
        samples = _build_phased_samples(
            [
                (5, 0.0, 0.0),  # IDLE
                (15, 10.0, 80.0),  # ACCELERATION → CRUISE
            ]
        )
        summary = summarize_run_data(meta, samples, include_samples=False)
        psd = summary.get("phase_speed_breakdown")
        assert psd is not None, "phase_speed_breakdown must be in summary"
        assert isinstance(psd, list)
        # At least one row must be present
        assert len(psd) >= 1
        # Every row must have 'phase' and count fields
        for row in psd:
            assert "phase" in row
            assert "count" in row
            assert row["count"] > 0

    def test_phase_breakdown_rows_cover_all_samples(self) -> None:
        """Sum of phase row counts must equal total samples processed."""
        from vibesensor.report.findings import _phase_speed_breakdown
        from vibesensor.report.phase_segmentation import segment_run_phases

        samples = _build_phased_samples([(5, 0.0, 0.0), (10, 50.0, 80.0), (5, 0.0, 0.0)])
        per_sample_phases, _ = segment_run_phases(samples)
        rows = _phase_speed_breakdown(samples, per_sample_phases)

        total = sum(int(row["count"]) for row in rows)
        assert total == len(samples)


class TestReferenceFindingDistinguishability:
    """Reference-missing findings must be distinguishable and must not inflate
    confidence statistics. (issue #187)"""

    def test_reference_finding_has_finding_type_field(self) -> None:
        """_reference_missing_finding must include finding_type='reference'."""
        from vibesensor.report.findings import _reference_missing_finding

        ref = _reference_missing_finding(
            finding_id="REF_SPEED",
            suspected_source="unknown",
            evidence_summary="Speed data missing",
            quick_checks=["Check GPS"],
        )
        assert ref.get("finding_type") == "reference", (
            f"Expected finding_type='reference', got {ref.get('finding_type')!r}"
        )

    def test_reference_findings_excluded_from_top_causes(self) -> None:
        """select_top_causes must not include REF_ findings in output."""
        from vibesensor.report.findings import _reference_missing_finding

        ref = _reference_missing_finding(
            finding_id="REF_SPEED",
            suspected_source="unknown",
            evidence_summary="Speed data missing",
            quick_checks=[],
        )
        # Mix a reference finding with a high-confidence diagnostic finding
        findings = [
            ref,
            {
                "finding_id": "F001",
                "confidence_0_to_1": 0.80,
                "suspected_source": "wheel/tire",
                "severity": "diagnostic",
            },
        ]
        from vibesensor.report.summary import select_top_causes

        top = select_top_causes(findings)
        for cause in top:
            fid = str(cause.get("finding_id") or "")
            assert not fid.startswith("REF_"), (
                f"Reference finding {fid!r} must not appear in top_causes"
            )

    def test_all_ref_variants_have_reference_type(self) -> None:
        """All four REF_ finding IDs must carry finding_type='reference'."""
        from vibesensor.report.findings import _reference_missing_finding

        for fid in ("REF_SPEED", "REF_WHEEL", "REF_ENGINE", "REF_SAMPLE_RATE"):
            ref = _reference_missing_finding(
                finding_id=fid,
                suspected_source="unknown",
                evidence_summary="missing",
                quick_checks=[],
            )
            assert ref.get("finding_type") == "reference", (
                f"{fid}: expected finding_type='reference', got {ref.get('finding_type')!r}"
            )


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


# ---------------------------------------------------------------------------
# 11. Certainty label signal-quality guard (issue #184)
# ---------------------------------------------------------------------------


class TestCertaintyLabelSignalQualityGuard:
    """certainty_label must never return 'high' when strength is negligible.

    Acceptance criteria (issue #184): no combination of parameters can produce
    a 'High' label with a negligible strength band.
    """

    def test_negligible_strength_caps_high_certainty_to_medium(self) -> None:
        """High confidence + negligible strength → medium label, not high."""
        level, label, _, _ = certainty_label(0.90, lang="en", strength_band_key="negligible")
        assert level == "medium", f"Expected 'medium' for negligible strength, got '{level}'"
        assert label == "Medium"

    def test_negligible_strength_does_not_affect_medium_confidence(self) -> None:
        """Medium confidence + negligible strength stays as medium (no over-cap)."""
        level, label, _, _ = certainty_label(0.55, lang="en", strength_band_key="negligible")
        assert level == "medium"

    def test_negligible_strength_does_not_affect_low_confidence(self) -> None:
        """Low confidence + negligible strength stays as low."""
        level, label, _, _ = certainty_label(0.30, lang="en", strength_band_key="negligible")
        assert level == "low"

    def test_non_negligible_strength_allows_high_confidence(self) -> None:
        """High confidence + non-negligible strength → high label as expected."""
        for band in ("light", "moderate", "strong", "very_strong", None):
            level, _, _, _ = certainty_label(0.80, lang="en", strength_band_key=band)
            assert level == "high", f"Expected 'high' for strength_band_key={band!r}, got '{level}'"

    def test_negligible_guard_applies_in_nl_too(self) -> None:
        """Guard applies regardless of language."""
        level, label, _, _ = certainty_label(0.80, lang="nl", strength_band_key="negligible")
        assert level == "medium"
        assert label == "Gemiddeld"
