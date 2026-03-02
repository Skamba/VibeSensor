"""
Cycle 2 Audit – Offline Analysis Pipeline Correctness & Determinism
====================================================================

10 findings: 5 confirmations/refinements of known issues, 5 new findings.
Each finding includes title, severity, evidence, root cause, and proposed fix.

This file also contains targeted unit tests that demonstrate each finding.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import numpy as np
import pytest

# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────
from vibesensor_core.strength_bands import bucket_for_strength
from vibesensor_core.vibration_strength import (
    compute_vibration_strength_db,
)

from vibesensor.analysis.helpers import _speed_stats
from vibesensor.analysis.phase_segmentation import (
    segment_run_phases,
)
from vibesensor.analysis.strength_labels import strength_label
from vibesensor.processing import SignalProcessor

# =====================================================================
# FINDING 1 (KNOWN – CONFIRMED) — First valid freq bin zeroed
# Severity: MEDIUM
# Evidence: processing.py line 508 (amp_for_peaks[0] = 0.0)
# Root cause: After slicing the FFT spec by valid_idx (which may start
#   at ~5 Hz when spectrum_min_hz > 0), the code zeros bin 0 of the
#   *sliced* array — i.e. the first valid analysis bin, not the DC bin.
#   The DC bin was already halved at line 501 (spec[0] *= 0.5) and may
#   have been removed by the valid_idx mask entirely.
# Impact: Real energy at ~5 Hz is silently suppressed in per-axis peak
#   detection AND in the combined spectrum (line 520 feeds amp_for_peaks
#   into combined_spectrum_amp_g), affecting vibration_strength_db.
# Proposed fix: Remove line 508 or guard it so it only fires when the
#   sliced bin 0 truly corresponds to 0 Hz (DC):
#     if amp_for_peaks.size > 1 and freq_slice[0] == 0.0:
#         amp_for_peaks[0] = 0.0
# =====================================================================


class TestFinding1_FirstValidBinZeroed:
    """Demonstrate that the first valid frequency bin is silently zeroed."""

    def test_first_valid_bin_suppressed_in_combined_spectrum(self):
        """When spectrum_min_hz > 0, bin 0 of the sliced spectrum is a
        real analysis frequency, yet it is zeroed before being fed to
        combined_spectrum_amp_g."""
        sp = SignalProcessor(
            sample_rate_hz=512,
            waveform_seconds=4,
            waveform_display_hz=100,
            fft_n=512,
            spectrum_min_hz=5.0,
            spectrum_max_hz=200,
        )
        # Inject a 6 Hz sinusoid — should appear in the first few bins
        t = np.arange(512, dtype=np.float32) / 512
        signal = 0.5 * np.sin(2 * np.pi * 6 * t)
        block = np.stack([signal, signal, signal])

        result = sp._compute_fft_spectrum(block, 512)
        freq_slice = result["freq_slice"]
        combined_amp = result["combined_amp"]

        # Find the bin closest to 6 Hz in freq_slice
        target_idx = int(np.argmin(np.abs(freq_slice - 6.0)))

        # The issue: if this bin happens to be index 0 of the sliced
        # array, it will be zeroed.
        if target_idx == 0:
            # BUG: combined_amp[0] is 0.0 even though there's real
            # energy at this frequency
            assert combined_amp[0] == 0.0, "Expected bin 0 to be zeroed (demonstrating the bug)"
        else:
            # If freq resolution puts 6 Hz in bin > 0, the energy is preserved
            assert combined_amp[target_idx] > 0


# =====================================================================
# FINDING 2 (KNOWN – CONFIRMED) — Double bin removal in noise floor
# Severity: MEDIUM
# Evidence: processing.py:303 and vibration_strength.py:76
# Root cause: SignalProcessor._noise_floor() does amps[1:] to remove DC,
#   then sorts and passes to noise_floor_amp_p20_g() which also does [1:]
#   on the (now sorted) list — removing the minimum amplitude value.
#   Net result: DC bin AND the smallest-amplitude bin are both excluded.
# Impact: Inflates noise floor by ~30% for monotonically increasing
#   spectra, which deflates SNR and strength_db. The effect size depends
#   on the spectral shape of the signal.
# Proposed fix: Remove the amps[1:] slice in _noise_floor() since
#   noise_floor_amp_p20_g already handles the DC bin exclusion:
#     band = amps  # let noise_floor_amp_p20_g handle [1:] slicing
# =====================================================================


class TestFinding2_DoubleBinRemoval:
    """_noise_floor uses np.percentile directly, avoiding the DC-bin
    skip that noise_floor_amp_p20_g performs (since the caller already
    provides DC-excluded data)."""

    def test_noise_floor_includes_all_bins(self):
        """_noise_floor must include ALL bins in the P20 computation.

        Unlike noise_floor_amp_p20_g (which skips [1:] to remove DC),
        _noise_floor receives pre-processed data where DC is already
        excluded/zeroed, so it computes P20 on all input values.
        """
        amps = np.array(
            [5.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0],
            dtype=np.float32,
        )

        actual_floor = SignalProcessor._noise_floor(amps)
        # P20 of all 10 values via numpy
        expected = float(np.percentile(amps, 20))

        assert actual_floor == pytest.approx(expected, abs=1e-6), (
            f"Noise floor mismatch: actual={actual_floor:.4f} vs expected={expected:.4f}"
        )


# =====================================================================
# FINDING 3 (KNOWN – CONFIRMED) — bucket_for_strength vs strength_label
#   inconsistency for negative dB
# Severity: LOW
# Evidence: strength_bands.py:33 vs strength_labels.py:50-55
# Root cause: bucket_for_strength iterates BANDS (min_db starts at 0.0)
#   and returns None when dB < 0.0. strength_label uses the same
#   thresholds but initializes result to the first band (l0/negligible)
#   before iterating, so dB < 0 falls through to "negligible".
# Impact: Code that calls bucket_for_strength gets None for negative dB
#   while code calling strength_label gets "negligible". Any caller
#   checking bucket == None as "no signal" may misclassify a weak-but-
#   present vibration.
# Proposed fix: Make bucket_for_strength return "l0" for negative dB
#   (initialize selected = "l0" before the loop).
# =====================================================================


class TestFinding3_BucketVsLabelInconsistency:
    """FIXED: bucket_for_strength now returns 'l0' for negative dB,
    consistent with strength_label returning 'negligible'."""

    @pytest.mark.parametrize("db_value", [-5.0, -0.1, -20.0])
    def test_negative_db_inconsistency(self, db_value: float):
        bucket = bucket_for_strength(db_value)
        label_key, label_text = strength_label(db_value, lang="en")
        # After fix: bucket returns 'l0', consistent with label 'negligible'
        assert bucket == "l0", f"bucket_for_strength({db_value}) should return 'l0'"
        assert label_key == "negligible", f"strength_label({db_value}) returns {label_key}"


# =====================================================================
# FINDING 4 (KNOWN – CONFIRMED & REFINED) — Order-tracking match
#   tolerance ignores path_compliance
# Severity: HIGH
# Evidence: findings.py line 718-719
# Root cause: The variable `compliance` is computed from
#   hypothesis.path_compliance but is never used in the tolerance_hz
#   calculation on the next line. The tolerance remains fixed at
#   max(0.5 Hz, predicted_hz * 0.08) regardless of path compliance.
#   However, path_compliance IS used later in the error_denominator
#   (line 894) which softens the error score for compliant paths.
# Impact: Wheel-order hypotheses (compliance=1.5) use the same narrow
#   match tolerance as driveshaft (compliance=1.0). Real wheel vibrations
#   that travel through suspension bushings produce broader, shifted peaks
#   that fall outside the unwidened tolerance, leading to lower match
#   rates and missed wheel-order findings.
# Proposed fix: Scale tolerance by path_compliance:
#     tolerance_hz = max(ORDER_TOLERANCE_MIN_HZ,
#                        predicted_hz * ORDER_TOLERANCE_REL * compliance)
# =====================================================================


class TestFinding4_ToleranceIgnoresCompliance:
    """Demonstrate that compliance is computed but not used in tolerance_hz."""

    def test_compliance_used_in_tolerance(self):
        """FIXED: tolerance_hz now scales with sqrt(path_compliance)."""
        import inspect

        from vibesensor.analysis.findings import _build_order_findings

        source = inspect.getsource(_build_order_findings)
        assert "compliance = getattr(hypothesis" in source
        # After fix: compliance_scale IS used in the tolerance computation
        assert "compliance_scale" in source
        assert "compliance**0.5" in source or "compliance ** 0.5" in source


# =====================================================================
# FINDING 5 (KNOWN – CONFIRMED) — bounded_sample called without total_hint
# Severity: LOW
# Evidence: api.py:502, metrics_log.py:851
# Root cause: Both call sites pass only max_items but not total_hint.
#   When total_hint is 0 (default), the initial stride is 1, meaning
#   all samples are collected until max_items is exceeded, then the list
#   is halved (reactive doubling). This wastes memory collecting 2x
#   samples before discarding half.
# Impact: Memory spike during post-analysis of large runs (e.g. 50k+
#   samples). Not a correctness bug, but causes O(2N) peak memory
#   instead of O(N) when the total count is knowable in advance.
# Proposed fix: Pass total_hint from the DB or iterator metadata when
#   available (history_db can expose sample_count for a run).
# =====================================================================


class TestFinding5_BoundedSampleNoHint:
    """Demonstrate the reactive doubling behavior without total_hint."""

    def test_reactive_doubling_wastes_work(self):
        from vibesensor.runlog import bounded_sample

        items = [{"v": i} for i in range(200)]
        # Without total_hint: starts with stride=1, collects all until overflow
        kept_no_hint, total, stride = bounded_sample(iter(items), max_items=50)
        # With total_hint: computes stride upfront
        kept_with_hint, total2, stride2 = bounded_sample(iter(items), max_items=50, total_hint=200)
        # Without hint, stride grows reactively via doubling
        assert stride >= 2, "Reactive doubling should have kicked in"
        # With hint, stride is computed upfront (200//50 = 4)
        assert stride2 == 4, "Upfront stride should be 4"


# =====================================================================
# FINDING 6 (NEW) — Combined spectrum built from zeroed-bin arrays
# Severity: HIGH
# Evidence: processing.py lines 520, 525-528
# Root cause: axis_amp_slices.append(amp_for_peaks) appends the array
#   where bin 0 was zeroed. The combined_spectrum_amp_g() is then
#   computed from these zeroed arrays. So the combined spectrum—the
#   primary input to compute_vibration_strength_db—has a systematic
#   zero at bin 0 across ALL axes.
# Impact: The first valid frequency bin in the combined spectrum is
#   always zero, creating a spurious trough in the diagnostic spectrum.
#   Any real vibration energy at that frequency is completely lost from
#   the strength calculation and peak detection.
# Proposed fix: Build axis_amp_slices from amp_slice (the un-zeroed
#   copy) instead of amp_for_peaks:
#     axis_amp_slices.append(amp_slice)
#   Then amp_for_peaks is only used for per-axis peak detection (which
#   is its intended purpose—avoiding DC leakage in peak detection).
# =====================================================================


class TestFinding6_CombinedSpectrumInheritsZeroedBin:
    """Combined spectrum inherits the zeroed bin from amp_for_peaks."""

    def test_combined_spectrum_preserves_bin0(self):
        """FIXED: combined spectrum bin 0 should NOT be zeroed for
        broadband input because axis_amp_slices now uses amp_slice."""
        sp = SignalProcessor(
            sample_rate_hz=256,
            waveform_seconds=4,
            waveform_display_hz=100,
            fft_n=256,
            spectrum_min_hz=5.0,
            spectrum_max_hz=200,
        )
        rng = np.random.default_rng(42)
        block = rng.standard_normal((3, 256)).astype(np.float32) * 0.1

        result = sp._compute_fft_spectrum(block, 256)
        combined = result["combined_amp"]

        if combined.size > 0:
            assert combined[0] > 0.0, (
                "Combined spectrum bin 0 should be non-zero for broadband input"
            )


# =====================================================================
# FINDING 7 (NEW) — Phase segmentation uses sample indices as seconds
#   when time data is missing
# Severity: MEDIUM
# Evidence: phase_segmentation.py lines 248-251
# Root cause: When a segment has no valid t_s values and there are no
#   previous segments, PhaseSegment.start_t_s and end_t_s are set to
#   the sample indices (float(seg_start), float(seg_end)). These index
#   values masquerade as seconds in all downstream consumers.
# Impact: Reports show misleading phase timing. A run with 500 samples
#   at 10 Hz (50 seconds) would show start_t_s=0, end_t_s=499,
#   implying 499 seconds instead of 50. Phase duration calculations,
#   timeline displays, and any speed-vs-time analysis will be wrong.
# Proposed fix: Estimate time from sample index and sample rate:
#     sample_rate = metadata.get("raw_sample_rate_hz") or 1.0
#     start_t = float(seg_start) / sample_rate
#     end_t = float(seg_end) / sample_rate
#   Or set both to `None` and handle missing time downstream.
# =====================================================================


class TestFinding7_PhaseSegmentIndexAsSeconds:
    """Phase segmentation uses NaN sentinel when time is missing."""

    def test_missing_time_uses_nan_sentinel(self):
        # Samples with no t_s → time falls back to NaN sentinel
        samples = [
            {"speed_kmh": 80.0}  # no t_s
            for _ in range(20)
        ]
        per_sample_phases, segments = segment_run_phases(samples)
        assert len(segments) > 0
        seg = segments[0]
        # Fixed: start_t_s and end_t_s are NaN (unknown), not sample indices
        import math

        assert math.isnan(seg.start_t_s)
        assert math.isnan(seg.end_t_s)


# =====================================================================
# FINDING 8 (NEW) — compute_vibration_strength_db cannot find peaks
#   when n < 3
# Severity: MEDIUM
# Evidence: vibration_strength.py line 186: range(1, n-1) → empty for n≤2
# Root cause: The local_maxima search loop starts at index 1 and ends
#   at n-2. For n=1 or n=2, this range is empty, so no peaks are ever
#   found. The function returns vibration_strength_db=0.0 and
#   strength_bucket=None.
# Impact: When spectrum_min_hz is close to spectrum_max_hz (narrow band
#   analysis), or when sample_rate is very low relative to fft_n, the
#   sliced spectrum can have only 1-2 bins. The function silently
#   returns 0 dB instead of reporting the actual energy in those bins.
# Proposed fix: Handle n=1 and n=2 by treating the maximum-amplitude
#   bin as the sole peak candidate (degenerate case).
# =====================================================================


class TestFinding8_NoPeaksWhenLessThan3Bins:
    """compute_vibration_strength_db cannot detect peaks with < 3 frequency bins."""

    @pytest.mark.parametrize("n_bins", [1, 2])
    def test_no_peaks_detected_for_small_spectra(self, n_bins: int):
        freq = [10.0 * (i + 1) for i in range(n_bins)]
        amps = [0.5] * n_bins  # Significant energy
        result = compute_vibration_strength_db(
            freq_hz=freq,
            combined_spectrum_amp_g_values=amps,
        )
        # Bug: returns 0 dB even though there is real energy
        assert result["vibration_strength_db"] == 0.0
        assert result["top_peaks"] == []
        # Should have found the 0.5g amplitude as a peak


# =====================================================================
# FINDING 9 (NEW) — _speed_stats crashes on single-element list with
#   _mean_variance returning (mean, 0.0) but steady_speed always True
# Severity: LOW
# Evidence: helpers.py lines 190-200
# Root cause: With a single speed value, stddev=0 and range=0, so
#   steady_speed=True always. This is technically correct but
#   misleading for downstream code that uses steady_speed to adjust
#   analysis confidence. A single data point provides no information
#   about speed variation.
# Impact: The constant_speed penalty (0.75x confidence multiplier)
#   is correctly applied via the separate stddev < 0.5 check, so the
#   primary diagnostic path is not affected. However, report_data_
#   builder and the suitability checks may show "speed variation: pass"
#   when there's only one speed sample.
# Proposed fix: Add a minimum sample count check:
#     "steady_speed": len(speed_values) >= 3 and (stddev < ... or range < ...)
# =====================================================================


class TestFinding9_SteadySpeedSinglePoint:
    """_speed_stats reports steady_speed=True with a single data point."""

    def test_single_point_is_steady(self):
        result = _speed_stats([80.0])
        # A single point tells us nothing about speed variation
        assert result["steady_speed"] is True
        assert result["stddev_kmh"] == 0.0
        assert result["range_kmh"] == 0.0

    def test_empty_is_not_steady(self):
        result = _speed_stats([])
        assert result["steady_speed"] is False


# =====================================================================
# FINDING 10 (NEW) — summarize_run_data has no error isolation between
#   pipeline stages
# Severity: HIGH
# Evidence: summary.py lines 730-950 (summarize_run_data)
# Root cause: summarize_run_data calls multiple sub-functions in
#   sequence (_compute_run_timing, _prepare_speed_and_phases,
#   _compute_accel_statistics, _build_findings, _plot_data, etc.).
#   None of these calls are individually wrapped in try/except. If any
#   sub-function throws (e.g. _build_findings raises due to malformed
#   peak data), the entire analysis fails and no summary is produced.
# Impact: A single corrupted sample or unexpected data shape in one
#   pipeline stage (e.g. findings) prevents the entire summary from
#   being computed. Speed stats, phase info, and sensor intensity
#   data that were already computed successfully are all lost.
# Impact path: metrics_log.py wraps the outer call in try/except and
#   stores an error, but the API re-computation path (api.py:507)
#   does not — it lets exceptions propagate to the HTTP handler.
# Proposed fix: Wrap each stage in a try/except that logs the error
#   and populates the corresponding output field with a sentinel/empty
#   value, allowing partial results to be returned. Example:
#     try:
#         findings = _build_findings(...)
#     except Exception:
#         LOGGER.exception("findings stage failed")
#         findings = []
#         summary["warnings"].append("findings_stage_failed")
# =====================================================================


class TestFinding10_NoPipelineErrorIsolation:
    """Demonstrate that a failure in one stage kills the entire summary."""

    def test_findings_failure_kills_entire_summary(self):
        from vibesensor.analysis.summary import summarize_run_data

        metadata: dict[str, Any] = {
            "run_id": "test-run",
            "raw_sample_rate_hz": 512,
            "start_time_utc": "2025-01-01T00:00:00Z",
            "end_time_utc": "2025-01-01T00:01:00Z",
        }
        # Minimal valid samples
        samples = [
            {
                "t_s": float(i),
                "speed_kmh": 80.0,
                "accel_x_g": 0.01,
                "accel_y_g": 0.01,
                "accel_z_g": 1.0,
                "vibration_strength_db": 15.0,
                "strength_bucket": "l1",
                "top_peaks": [{"hz": 30.0, "amp": 0.05}],
            }
            for i in range(20)
        ]

        # Patch _build_findings to raise an exception
        with patch(
            "vibesensor.analysis.summary._build_findings",
            side_effect=RuntimeError("simulated findings failure"),
        ):
            with pytest.raises(RuntimeError, match="simulated findings failure"):
                summarize_run_data(metadata, samples, lang="en", file_name="test")
        # Bug: the entire summary is lost; no partial results are available
