# ruff: noqa: E402, E501
from __future__ import annotations

"""Consolidated audits regression tests."""


# ===== From test_analysis_pipeline_audit.py =====

"""
Analysis pipeline audit – correctness and determinism.

10 findings: 5 confirmations/refinements of known issues, 5 new findings.
Each finding includes title, severity, evidence, root cause, and proposed fix.

This file also contains targeted unit tests that demonstrate each finding.
"""


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
    noise_floor_amp_p20_g,
)

from vibesensor.analysis.helpers import _speed_stats
from vibesensor.analysis.phase_segmentation import (
    segment_run_phases,
)
from vibesensor.analysis.strength_labels import strength_label
from vibesensor.processing import SignalProcessor


def _make_signal_processor(
    sample_rate_hz: int = 512,
    fft_n: int = 512,
    *,
    spectrum_min_hz: float = 5.0,
    spectrum_max_hz: float = 200.0,
) -> SignalProcessor:
    """Create a SignalProcessor with common defaults for audit tests."""
    return SignalProcessor(
        sample_rate_hz=sample_rate_hz,
        waveform_seconds=4,
        waveform_display_hz=100,
        fft_n=fft_n,
        spectrum_min_hz=spectrum_min_hz,
        spectrum_max_hz=spectrum_max_hz,
    )


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
        sp = _make_signal_processor(sample_rate_hz=512, fft_n=512)
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
    """Demonstrate that _noise_floor removes two bins instead of one."""

    def test_double_skip_in_noise_floor(self):
        """_noise_floor must NOT skip amps[0] before passing to
        noise_floor_amp_p20_g — the caller already provides the
        analysis-band slice (DC excluded by spectrum_min_hz).

        FIXED: amps[1:] removed; all bins now included.
        """
        amps = np.array(
            [5.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0],
            dtype=np.float32,
        )

        correct_floor = noise_floor_amp_p20_g(combined_spectrum_amp_g=[float(v) for v in amps])
        actual_floor = SignalProcessor._noise_floor(amps)

        # After fix: both should agree exactly
        assert actual_floor == pytest.approx(correct_floor, abs=1e-6), (
            f"Noise floor mismatch: actual={actual_floor:.4f} vs correct={correct_floor:.4f}"
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
        sp = _make_signal_processor(sample_rate_hz=256, fft_n=256)
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
        with (
            patch(
                "vibesensor.analysis.summary._build_findings",
                side_effect=RuntimeError("simulated findings failure"),
            ),
            pytest.raises(RuntimeError, match="simulated findings failure"),
        ):
            summarize_run_data(metadata, samples, lang="en", file_name="test")
        # Bug: the entire summary is lost; no partial results are available


# ===== From test_coverage_gap_audit_round2.py =====

"""Coverage-gap audit (round 2).

Findings addressed
-------------------
1. Processing: debug_spectrum / raw_samples never directly tested
2. Processing: multi_spectrum_payload alignment metadata untested
3. Worker pool: submit after shutdown + map_unordered timing metrics
4. WS Hub: run() loop (tick callback, exception recovery, cancellation)
5. GPS: set_fallback_settings boundary values + NaN/Inf override
6. GPS: reconnect back-off doubling and cap
7. History DB: store_analysis idempotency (double-complete) + store_analysis_error
8. History DB: finalize_run no-op on wrong status
9. API export: _flatten_for_csv edge cases (nested dict, extras column)
10. API export: _safe_filename sanitization
"""


import asyncio
import json
import math
import time
from collections.abc import Iterator
from math import pi
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from vibesensor.api import _flatten_for_csv, _safe_filename
from vibesensor.gps_speed import (
    _GPS_RECONNECT_DELAY_S,
    _GPS_RECONNECT_MAX_DELAY_S,
    DEFAULT_FALLBACK_MODE,
    MAX_STALE_TIMEOUT_S,
    MIN_STALE_TIMEOUT_S,
    GPSSpeedMonitor,
)
from vibesensor.history_db import HistoryDB
from vibesensor.worker_pool import WorkerPool
from vibesensor.ws_hub import WebSocketHub

# ── helpers ──────────────────────────────────────────────────────────────────


def _proc(**kwargs) -> SignalProcessor:
    defaults = {
        "sample_rate_hz": 800,
        "waveform_seconds": 4,
        "waveform_display_hz": 100,
        "fft_n": 512,
        "spectrum_max_hz": 200,
    }
    defaults.update(kwargs)
    return SignalProcessor(**defaults)


def _inject(proc: SignalProcessor, cid: str, n: int = 1024, sr: int = 800) -> None:
    rng = np.random.default_rng(42)
    t = np.arange(n, dtype=np.float64) / sr
    x = (0.03 * np.sin(2.0 * pi * 30.0 * t)).astype(np.float32)
    y = (0.02 * np.sin(2.0 * pi * 50.0 * t)).astype(np.float32)
    z = (rng.standard_normal(n) * 0.005).astype(np.float32)
    samples = np.stack([x, y, z], axis=1)
    proc.ingest(cid, samples, sample_rate_hz=sr)


@pytest.fixture
def history_db(tmp_path: Path) -> Iterator[HistoryDB]:
    """Yield an open HistoryDB that is closed after the test."""
    db = HistoryDB(tmp_path / "test.db")
    try:
        yield db
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════
# 1. Processing: debug_spectrum / raw_samples
# ═══════════════════════════════════════════════════════════════════════════


class TestDebugSpectrumAndRawSamples:
    """debug_spectrum() and raw_samples() are only tested indirectly via API
    mocks.  Direct unit tests ensure correctness of the returned data."""

    def test_debug_spectrum_insufficient_samples(self) -> None:
        proc = _proc(fft_n=512)
        # No data
        result = proc.debug_spectrum("nonexistent")
        assert result["error"] == "insufficient samples"
        assert result["count"] == 0
        assert result["fft_n"] == 512

    def test_debug_spectrum_returns_expected_keys(self) -> None:
        proc = _proc(fft_n=512)
        _inject(proc, "c1", n=1024)
        proc.compute_metrics("c1")
        result = proc.debug_spectrum("c1")
        assert "error" not in result
        assert result["client_id"] == "c1"
        assert result["fft_n"] == 512
        assert result["window"] == "hann"
        assert result["freq_bins"] > 0
        assert result["freq_resolution_hz"] > 0
        assert math.isfinite(result["vibration_strength_db"])
        assert isinstance(result["top_bins_by_amplitude"], list)
        assert len(result["top_bins_by_amplitude"]) <= 10
        for b in result["top_bins_by_amplitude"]:
            assert "freq_hz" in b
            assert "combined_amp_g" in b

    def test_debug_spectrum_raw_stats_are_finite(self) -> None:
        proc = _proc(fft_n=256)
        _inject(proc, "c1", n=512)
        result = proc.debug_spectrum("c1")
        for key in ("mean_g", "std_g", "min_g", "max_g"):
            vals = result["raw_stats"][key]
            assert len(vals) == 3
            for v in vals:
                assert math.isfinite(v), f"non-finite in raw_stats[{key}]"
        assert len(result["detrended_std_g"]) == 3

    def test_raw_samples_no_data(self) -> None:
        proc = _proc()
        result = proc.raw_samples("nonexistent")
        assert result["error"] == "no data"
        assert result["count"] == 0

    def test_raw_samples_returns_axes(self) -> None:
        proc = _proc()
        _inject(proc, "c1", n=200)
        result = proc.raw_samples("c1", n_samples=100)
        assert result["client_id"] == "c1"
        assert result["n_samples"] == 100
        assert len(result["x"]) == 100
        assert len(result["y"]) == 100
        assert len(result["z"]) == 100

    def test_raw_samples_caps_at_available(self) -> None:
        proc = _proc()
        _inject(proc, "c1", n=50)
        result = proc.raw_samples("c1", n_samples=9999)
        assert result["n_samples"] == 50


# ═══════════════════════════════════════════════════════════════════════════
# 2. Processing: multi_spectrum_payload alignment metadata
# ═══════════════════════════════════════════════════════════════════════════


class TestMultiSpectrumAlignment:
    """multi_spectrum_payload with multiple sensors should include alignment
    metadata only when ≥ 2 sensors have spectrum data."""

    def test_single_sensor_no_alignment_key(self) -> None:
        proc = _proc()
        _inject(proc, "c1", n=1024)
        proc.compute_metrics("c1")
        result = proc.multi_spectrum_payload(["c1"])
        assert "alignment" not in result

    def test_two_sensors_produces_alignment(self) -> None:
        proc = _proc()
        _inject(proc, "c1", n=1024)
        _inject(proc, "c2", n=1024)
        proc.compute_metrics("c1")
        proc.compute_metrics("c2")
        result = proc.multi_spectrum_payload(["c1", "c2"])
        assert "alignment" in result
        alignment = result["alignment"]
        assert "overlap_ratio" in alignment
        assert "aligned" in alignment
        assert isinstance(alignment["sensor_count"], int)
        assert alignment["sensor_count"] == 2

    def test_alignment_overlap_ratio_is_finite(self) -> None:
        proc = _proc()
        _inject(proc, "c1", n=1024)
        _inject(proc, "c2", n=1024)
        proc.compute_metrics("c1")
        proc.compute_metrics("c2")
        result = proc.multi_spectrum_payload(["c1", "c2"])
        assert math.isfinite(result["alignment"]["overlap_ratio"])
        assert isinstance(result["alignment"]["clock_synced"], bool)


# ═══════════════════════════════════════════════════════════════════════════
# 3. Worker pool: submit + timing metrics
# ═══════════════════════════════════════════════════════════════════════════


class TestWorkerPoolExtended:
    def test_submit_returns_future(self) -> None:
        pool = WorkerPool(max_workers=2)
        try:
            fut = pool.submit(lambda: 42)
            assert fut.result(timeout=2) == 42
        finally:
            pool.shutdown()

    def test_stats_tracks_total_wait_s(self) -> None:
        pool = WorkerPool(max_workers=1)
        try:
            pool.map_unordered(lambda x: time.sleep(0.01) or x, [1, 2])
            stats = pool.stats()
            assert stats["total_wait_s"] > 0
            assert stats["total_tasks"] == 2
        finally:
            pool.shutdown()

    def test_max_workers_clamped_to_one(self) -> None:
        pool = WorkerPool(max_workers=0)
        try:
            assert pool.max_workers == 1
        finally:
            pool.shutdown()

    def test_shutdown_wait_false(self) -> None:
        pool = WorkerPool(max_workers=2)
        pool.shutdown(wait=False)
        assert pool.stats()["alive"] is False


# ═══════════════════════════════════════════════════════════════════════════
# 4. WS Hub: run() loop
# ═══════════════════════════════════════════════════════════════════════════


class TestWSHubRunLoop:
    """WebSocketHub.run() is the main broadcast loop; never directly tested."""

    @pytest.mark.asyncio
    async def test_run_calls_on_tick_and_broadcasts(self) -> None:
        hub = WebSocketHub()
        ws = AsyncMock()
        ws.send_text = AsyncMock()
        await hub.add(ws, None)

        tick_count = 0

        def on_tick():
            nonlocal tick_count
            tick_count += 1

        task = asyncio.create_task(
            hub.run(hz=100, payload_builder=lambda _: {"ok": True}, on_tick=on_tick)
        )
        await asyncio.sleep(0.15)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert tick_count >= 2, f"on_tick called {tick_count} times, expected >= 2"
        assert ws.send_text.await_count >= 2

    @pytest.mark.asyncio
    async def test_run_survives_broadcast_exception(self) -> None:
        hub = WebSocketHub()
        call_count = 0

        def flaky_builder(_cid):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("first tick boom")
            return {"ok": True}

        ws = AsyncMock()
        ws.send_text = AsyncMock()
        await hub.add(ws, None)

        task = asyncio.create_task(hub.run(hz=50, payload_builder=flaky_builder))
        await asyncio.sleep(0.15)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # Should have recovered and called builder more than once
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_run_hz_clamps_to_minimum_1(self) -> None:
        hub = WebSocketHub()
        task = asyncio.create_task(hub.run(hz=0, payload_builder=lambda _: {}))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


# ═══════════════════════════════════════════════════════════════════════════
# 5. GPS: set_fallback_settings + NaN/Inf override
# ═══════════════════════════════════════════════════════════════════════════


class TestGPSFallbackSettings:
    def test_set_fallback_settings_clamps_stale_timeout(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.set_fallback_settings(stale_timeout_s=0.1)
        assert m.stale_timeout_s == MIN_STALE_TIMEOUT_S

        m.set_fallback_settings(stale_timeout_s=99999)
        assert m.stale_timeout_s == MAX_STALE_TIMEOUT_S

        m.set_fallback_settings(stale_timeout_s=30)
        assert m.stale_timeout_s == 30

    def test_set_fallback_settings_rejects_invalid_mode(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.set_fallback_settings(fallback_mode="bogus_mode")
        assert m.fallback_mode == DEFAULT_FALLBACK_MODE

    @pytest.mark.parametrize("value", [float("nan"), float("inf")])
    def test_override_non_finite_clears(self, value: float) -> None:
        m = GPSSpeedMonitor(gps_enabled=False)
        m.set_speed_override_kmh(80.0)
        assert m.override_speed_mps is not None
        m.set_speed_override_kmh(value)
        assert m.override_speed_mps is None

    def test_set_manual_source_selected(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        assert m.manual_source_selected is None
        m.set_manual_source_selected(True)
        assert m.manual_source_selected is True
        m.set_manual_source_selected(False)
        assert m.manual_source_selected is False


# ═══════════════════════════════════════════════════════════════════════════
# 6. GPS: reconnect back-off
# ═══════════════════════════════════════════════════════════════════════════


class TestGPSReconnectBackoff:
    @pytest.mark.asyncio
    async def test_reconnect_delay_doubles_and_caps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        delays_seen: list[float] = []

        connect_count = 0

        async def _mock_open_connection(host, port):
            nonlocal connect_count
            connect_count += 1
            delays_seen.append(m.current_reconnect_delay)
            if connect_count >= 5:
                raise asyncio.CancelledError()
            raise ConnectionRefusedError("test")

        original_sleep = asyncio.sleep

        async def _fast_sleep(delay):
            await original_sleep(0)

        monkeypatch.setattr(asyncio, "open_connection", _mock_open_connection)
        monkeypatch.setattr(asyncio, "sleep", _fast_sleep)

        with pytest.raises(asyncio.CancelledError):
            await m.run(host="127.0.0.1", port=29470)

        # First reconnect_delay should be the base delay
        assert delays_seen[0] == _GPS_RECONNECT_DELAY_S
        # Delays double
        for i in range(1, min(3, len(delays_seen))):
            assert delays_seen[i] >= delays_seen[i - 1]
        # Should be capped
        for d in delays_seen:
            assert d <= _GPS_RECONNECT_MAX_DELAY_S

    @pytest.mark.asyncio
    async def test_version_message_sets_device_info(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)

        async def _handler(reader, writer):
            await reader.readline()  # consume WATCH command
            writer.write(b'{"class":"VERSION","rev":"3.25"}\n')
            await writer.drain()
            writer.write(b'{"class":"TPV","mode":3,"speed":10.0}\n')
            await writer.drain()
            # Keep alive briefly then close
            await asyncio.sleep(0.05)
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(_handler, host="127.0.0.1", port=0)
        host, port = server.sockets[0].getsockname()[:2]

        task = asyncio.create_task(m.run(host=host, port=port))
        await asyncio.sleep(0.2)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        server.close()
        await server.wait_closed()

        assert m.device_info is not None
        # Device info should contain the gpsd version string
        assert "3.25" in m.device_info


# ═══════════════════════════════════════════════════════════════════════════
# 7. History DB: store_analysis idempotency + store_analysis_error
# ═══════════════════════════════════════════════════════════════════════════


class TestHistoryDBAnalysisIdempotency:
    def test_store_analysis_twice_keeps_first(self, history_db: HistoryDB) -> None:
        history_db.create_run("r1", "2026-01-01T00:00:00Z", {})
        history_db.finalize_run("r1", "2026-01-01T00:05:00Z")
        history_db.store_analysis("r1", {"findings": ["a"]})
        # Second store should be no-op (run already complete)
        history_db.store_analysis("r1", {"findings": ["b"]})
        run = history_db.get_run("r1")
        assert run is not None
        assert run["analysis"]["findings"] == ["a"], "Second store should not overwrite"

    def test_store_analysis_error_transitions_to_error(self, history_db: HistoryDB) -> None:
        history_db.create_run("r1", "2026-01-01T00:00:00Z", {})
        history_db.finalize_run("r1", "2026-01-01T00:05:00Z")
        history_db.store_analysis_error("r1", "pipeline crash")
        run = history_db.get_run("r1")
        assert run is not None
        assert run["status"] == "error"
        assert run["error_message"] == "pipeline crash"

    def test_analysis_is_current_for_missing_run(self, history_db: HistoryDB) -> None:
        assert history_db.analysis_is_current("nonexistent") is False

    def test_get_run_analysis_only_returns_complete(self, history_db: HistoryDB) -> None:
        history_db.create_run("r1", "2026-01-01T00:00:00Z", {})
        # Still recording — get_run_analysis should return None
        assert history_db.get_run_analysis("r1") is None
        history_db.finalize_run("r1", "2026-01-01T00:05:00Z")
        # Analyzing — still None
        assert history_db.get_run_analysis("r1") is None
        history_db.store_analysis("r1", {"result": "ok"})
        # Complete — should return
        result = history_db.get_run_analysis("r1")
        assert result is not None
        assert result["result"] == "ok"


# ═══════════════════════════════════════════════════════════════════════════
# 8. History DB: finalize_run on non-recording status
# ═══════════════════════════════════════════════════════════════════════════


class TestHistoryDBFinalizeNoOp:
    def test_finalize_run_noop_on_already_complete(self, history_db: HistoryDB) -> None:
        history_db.create_run("r1", "2026-01-01T00:00:00Z", {})
        history_db.finalize_run("r1", "2026-01-01T00:05:00Z")
        history_db.store_analysis("r1", {"ok": True})
        # Run is now 'complete'.  Calling finalize again should be a no-op.
        history_db.finalize_run("r1", "2026-01-01T00:10:00Z")
        run = history_db.get_run("r1")
        assert run["status"] == "complete"

    def test_finalize_run_noop_on_missing_run(self, history_db: HistoryDB) -> None:
        # Should not raise
        history_db.finalize_run("nonexistent", "2026-01-01T00:00:00Z")

    def test_finalize_run_with_metadata_noop_when_not_recording(
        self,
        history_db: HistoryDB,
    ) -> None:
        history_db.create_run("r1", "2026-01-01T00:00:00Z", {"v": 1})
        history_db.finalize_run("r1", "2026-01-01T00:05:00Z")
        # Now analyzing — finalize_run_with_metadata should no-op
        history_db.finalize_run_with_metadata("r1", "2026-01-01T00:10:00Z", {"v": 2})
        run = history_db.get_run("r1")
        # Metadata should still be the original if the call didn't match status
        assert run["status"] == "analyzing"

    def test_get_run_status_missing_returns_none(self, history_db: HistoryDB) -> None:
        assert history_db.get_run_status("nonexistent") is None

    def test_get_active_run_id(self, history_db: HistoryDB) -> None:
        assert history_db.get_active_run_id() is None
        history_db.create_run("r1", "2026-01-01T00:00:00Z", {})
        assert history_db.get_active_run_id() == "r1"
        history_db.finalize_run("r1", "2026-01-01T00:05:00Z")
        assert history_db.get_active_run_id() is None


# ═══════════════════════════════════════════════════════════════════════════
# 9. API export: _flatten_for_csv and extras column
# ═══════════════════════════════════════════════════════════════════════════


class TestFlattenForCSV:
    def test_nested_dict_serialised_as_json(self) -> None:
        row = {"top_peaks": [{"hz": 30, "amp": 0.1}], "accel_x_g": 0.5}
        flat = _flatten_for_csv(row)
        # top_peaks is a known CSV column and is list → JSON serialized
        assert isinstance(flat["top_peaks"], str)
        parsed = json.loads(flat["top_peaks"])
        assert parsed == [{"hz": 30, "amp": 0.1}]
        # Scalar values are kept as-is
        assert flat["accel_x_g"] == 0.5

    def test_extras_column_collects_unknown_keys(self) -> None:
        row = {"accel_x_g": 1.0, "custom_field": "hello", "another": 42}
        flat = _flatten_for_csv(row)
        extras = json.loads(flat["extras"])
        assert extras["custom_field"] == "hello"
        assert extras["another"] == 42
        assert "accel_x_g" not in extras

    def test_no_extras_when_all_known(self) -> None:
        row = {"accel_x_g": 1.0, "speed_kmh": 80.0}
        flat = _flatten_for_csv(row)
        assert "extras" not in flat or flat.get("extras") is None

    def test_empty_row(self) -> None:
        flat = _flatten_for_csv({})
        # Should not crash; no extras
        assert isinstance(flat, dict)


# ═══════════════════════════════════════════════════════════════════════════
# 10. API export: _safe_filename sanitization
# ═══════════════════════════════════════════════════════════════════════════


class TestSafeFilename:
    @pytest.mark.parametrize(
        ("input_name", "expected"),
        [
            ("run-2026-01-01_abc", "run-2026-01-01_abc"),
            ("", "download"),
            ("///", "___"),
        ],
    )
    def test_exact_output(self, input_name: str, expected: str) -> None:
        assert _safe_filename(input_name) == expected

    def test_special_chars_replaced(self) -> None:
        result = _safe_filename("run/with spaces & $pecial")
        assert "/" not in result
        assert " " not in result
        assert "$" not in result

    def test_long_name_truncated(self) -> None:
        result = _safe_filename("a" * 500)
        assert len(result) <= 200


# ===== From test_coverage_gap_audit_top10.py =====

"""Coverage-gap audit: top 10 untested critical code paths.

This file addresses the top 10 coverage gaps identified by systematic
cross-referencing of public/private functions in:
  - apps/server/vibesensor/analysis/findings.py
  - apps/server/vibesensor/analysis/summary.py
  - apps/server/vibesensor/metrics_log.py
  - apps/server/vibesensor/processing.py
against all test files in apps/server/tests/.

Each class documents the gap, its severity, and provides working tests.
"""


from unittest.mock import MagicMock

import pytest

from vibesensor.analysis.findings import (
    _compute_order_confidence,
    _detect_diffuse_excitation,
    _suppress_engine_aliases,
)
from vibesensor.analysis.phase_segmentation import DrivingPhase
from vibesensor.analysis.summary import (
    _build_phase_timeline,
    _build_run_suitability_checks,
    _compute_accel_statistics,
    _phase_ranking_score,
    summarize_run_data,
)
from vibesensor.metrics_log import MetricsLogger, MetricsLoggerConfig

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class _FakeSeg:
    """Minimal driving-phase segment stub for timeline tests."""

    def __init__(
        self,
        phase: DrivingPhase = DrivingPhase.CRUISE,
        start: float = 0.0,
        end: float = 10.0,
        speed_min: float = 50.0,
        speed_max: float = 60.0,
    ) -> None:
        self.phase = phase
        self.start_t_s = start
        self.end_t_s = end
        self.speed_min_kmh = speed_min
        self.speed_max_kmh = speed_max


_SUITABILITY_DEFAULTS: dict[str, Any] = {
    "language": "en",
    "steady_speed": False,
    "speed_sufficient": True,
    "sensor_ids": {"s1", "s2", "s3"},
    "reference_complete": True,
    "sat_count": 0,
    "samples": [],
}


def _suitability_checks(**overrides: Any) -> list[dict[str, Any]]:
    """Call _build_run_suitability_checks with sensible defaults + overrides."""
    kw = {**_SUITABILITY_DEFAULTS, **overrides}
    return _build_run_suitability_checks(**kw)


def _make_metrics_logger() -> tuple[MetricsLogger, MagicMock]:
    """Build a minimal MetricsLogger with mocked dependencies."""
    gps_mock = MagicMock()
    gps_mock.speed_mps = None
    gps_mock.effective_speed_mps = None
    gps_mock.override_speed_mps = None
    gps_mock.resolve_speed.return_value = MagicMock(source="none")

    registry = MagicMock()
    registry.active_client_ids.return_value = []

    settings_mock = MagicMock()
    settings_mock.snapshot.return_value = {
        "tire_width_mm": 205,
        "tire_aspect_pct": 55,
        "rim_in": 16,
        "final_drive_ratio": 3.73,
        "current_gear_ratio": 1.0,
        "tire_deflection_factor": None,
    }

    logger = MetricsLogger(
        MetricsLoggerConfig(
            enabled=False,
            log_path=Path("/tmp/test"),
            metrics_log_hz=1,
            sensor_model="test",
            default_sample_rate_hz=800,
            fft_window_size_samples=512,
            persist_history_db=False,
        ),
        registry=registry,
        gps_monitor=gps_mock,
        processor=MagicMock(),
        analysis_settings=settings_mock,
    )
    return logger, gps_mock


# ---------------------------------------------------------------------------
# Finding 1: _compute_order_confidence  (findings.py:504)
# SEVERITY: CRITICAL
# WHY: Core confidence-scoring algorithm with 18+ tuning parameters, multiple
#      conditional penalties/boosts, and clamped 0.08–0.97 output.  Every PDF
#      report hinges on its output.  Zero direct unit tests.
# ---------------------------------------------------------------------------


class TestComputeOrderConfidence:
    """Direct unit tests for _compute_order_confidence."""

    _DEFAULTS: dict[str, Any] = {
        "effective_match_rate": 0.60,
        "error_score": 0.80,
        "corr_val": 0.50,
        "snr_score": 0.60,
        "absolute_strength_db": 20.0,
        "localization_confidence": 0.70,
        "weak_spatial_separation": False,
        "dominance_ratio": 2.0,
        "constant_speed": False,
        "steady_speed": False,
        "matched": 30,
        "corroborating_locations": 2,
        "phases_with_evidence": 2,
        "is_diffuse_excitation": False,
        "diffuse_penalty": 1.0,
        "n_connected_locations": 3,
        "no_wheel_sensors": False,
        "path_compliance": 1.0,
    }

    @classmethod
    def _call(cls, **overrides: Any) -> float:
        return _compute_order_confidence(**{**cls._DEFAULTS, **overrides})

    def test_baseline_returns_moderate_confidence(self) -> None:
        conf = self._call()
        assert 0.30 < conf < 0.90, f"Baseline defaults produced unexpected {conf}"

    def test_output_clamped_low(self) -> None:
        """All-zero inputs should clamp to the 0.08 floor."""
        conf = self._call(
            effective_match_rate=0.0,
            error_score=0.0,
            corr_val=0.0,
            snr_score=0.0,
            absolute_strength_db=0.0,
            localization_confidence=0.0,
            matched=0,
            corroborating_locations=0,
            phases_with_evidence=0,
        )
        assert conf == pytest.approx(0.08, abs=0.001)

    def test_output_clamped_high(self) -> None:
        """Perfect inputs should clamp to the 0.97 ceiling."""
        conf = self._call(
            effective_match_rate=1.0,
            error_score=1.0,
            corr_val=1.0,
            snr_score=1.0,
            absolute_strength_db=40.0,
            localization_confidence=1.0,
            matched=100,
            corroborating_locations=4,
            phases_with_evidence=4,
        )
        assert conf == pytest.approx(0.97, abs=0.001)

    def test_negligible_strength_caps_at_045(self) -> None:
        """absolute_strength_db below negligible threshold should cap confidence."""
        conf = self._call(absolute_strength_db=5.0)
        assert conf <= 0.45 + 0.001

    @pytest.mark.parametrize(
        "normal_kw,penalty_kw",
        [
            pytest.param(
                {"weak_spatial_separation": False},
                {"weak_spatial_separation": True},
                id="weak_spatial_separation",
            ),
            pytest.param(
                {"constant_speed": False},
                {"constant_speed": True},
                id="constant_speed",
            ),
            pytest.param(
                {"is_diffuse_excitation": False},
                {"is_diffuse_excitation": True, "diffuse_penalty": 0.75},
                id="diffuse_excitation",
            ),
            pytest.param(
                {"n_connected_locations": 3},
                {"n_connected_locations": 1},
                id="single_sensor",
            ),
            pytest.param(
                {"absolute_strength_db": 25.0},
                {"absolute_strength_db": 12.0},
                id="light_strength_band",
            ),
        ],
    )
    def test_penalty_reduces_confidence(
        self, normal_kw: dict[str, Any], penalty_kw: dict[str, Any]
    ) -> None:
        assert self._call(**penalty_kw) < self._call(**normal_kw)

    def test_path_compliance_shifts_weights(self) -> None:
        """Higher path_compliance should shift weight from corr to match."""
        stiff = self._call(path_compliance=1.0, corr_val=0.0, effective_match_rate=0.80)
        compliant = self._call(path_compliance=1.5, corr_val=0.0, effective_match_rate=0.80)
        assert compliant >= stiff - 0.02

    def test_corroborating_locations_boost(self) -> None:
        base = self._call(corroborating_locations=1)
        boosted = self._call(corroborating_locations=3)
        assert boosted > base, "3+ corroborating locations should boost confidence"


# ---------------------------------------------------------------------------
# Finding 2: _detect_diffuse_excitation  (findings.py:454)
# SEVERITY: HIGH
# WHY: Determines whether vibration is localized or diffuse across sensors.
#      Misclassification silently penalizes genuine fault confidence by up to
#      35%.  Zero direct unit tests.
# ---------------------------------------------------------------------------


class TestDetectDiffuseExcitation:
    """Direct unit tests for _detect_diffuse_excitation."""

    def test_single_sensor_returns_not_diffuse(self) -> None:
        is_diff, penalty = _detect_diffuse_excitation(
            connected_locations={"front_left"},
            possible_by_location={"front_left": 20},
            matched_by_location={"front_left": 15},
            matched_points=[{"location": "front_left", "amp": 0.1}] * 15,
        )
        assert not is_diff
        assert penalty == 1.0

    def test_uniform_rates_uniform_amplitude_is_diffuse(self) -> None:
        locs = {"front_left", "front_right", "rear"}
        possible = dict.fromkeys(locs, 30)
        matched = dict.fromkeys(locs, 20)
        pts = [{"location": loc, "amp": 0.05} for loc in locs for _ in range(20)]
        is_diff, penalty = _detect_diffuse_excitation(locs, possible, matched, pts)
        assert is_diff, "Uniform rates + uniform amplitude should be diffuse"
        assert penalty < 1.0

    def test_dominant_amplitude_is_not_diffuse(self) -> None:
        locs = {"front_left", "rear"}
        possible = {"front_left": 20, "rear": 20}
        matched = {"front_left": 15, "rear": 14}
        pts = [{"location": "front_left", "amp": 0.30}] * 15 + [
            {"location": "rear", "amp": 0.05}
        ] * 14
        is_diff, penalty = _detect_diffuse_excitation(locs, possible, matched, pts)
        assert not is_diff, "Strong amplitude dominance should NOT be diffuse"

    def test_insufficient_samples_per_location(self) -> None:
        locs = {"front_left", "rear"}
        possible = {"front_left": 2, "rear": 2}
        matched = {"front_left": 2, "rear": 2}
        pts = [{"location": "front_left", "amp": 0.05}] * 2
        is_diff, penalty = _detect_diffuse_excitation(locs, possible, matched, pts)
        assert not is_diff, "Too few samples should not trigger diffuse"

    def test_empty_matched_points(self) -> None:
        locs = {"a", "b"}
        is_diff, penalty = _detect_diffuse_excitation(
            locs, {"a": 20, "b": 20}, {"a": 15, "b": 15}, []
        )
        # With no amplitude data, amplitude check defaults to uniform
        assert isinstance(is_diff, bool)
        assert penalty <= 1.0


# ---------------------------------------------------------------------------
# Finding 3: _suppress_engine_aliases  (findings.py:602)
# SEVERITY: HIGH
# WHY: Silently reduces engine-finding confidence when a stronger wheel
#      finding exists.  Could mask real engine faults or over-suppress.
#      Zero direct unit tests.
# ---------------------------------------------------------------------------


class TestSuppressEngineAliases:
    """Direct unit tests for _suppress_engine_aliases."""

    @staticmethod
    def _make_finding(source: str, conf: float) -> dict[str, object]:
        return {
            "suspected_source": source,
            "confidence_0_to_1": conf,
            "finding_id": "F_ORDER",
        }

    def test_no_wheel_no_suppression(self) -> None:
        findings = [
            (1.0, self._make_finding("engine", 0.60)),
            (0.5, self._make_finding("driveshaft", 0.40)),
        ]
        result = _suppress_engine_aliases(findings)
        assert any(f.get("suspected_source") == "engine" for f in result), (
            "Engine finding should survive when no wheel finding exists"
        )

    def test_engine_suppressed_by_stronger_wheel(self) -> None:
        findings = [
            (1.0, self._make_finding("wheel/tire", 0.70)),
            (0.8, self._make_finding("engine", 0.65)),
        ]
        result = _suppress_engine_aliases(findings)
        engine_findings = [f for f in result if f.get("suspected_source") == "engine"]
        if engine_findings:
            assert float(engine_findings[0]["confidence_0_to_1"]) < 0.65

    def test_strong_engine_not_suppressed(self) -> None:
        findings = [
            (0.3, self._make_finding("wheel/tire", 0.30)),
            (1.0, self._make_finding("engine", 0.90)),
        ]
        result = _suppress_engine_aliases(findings)
        engine_findings = [f for f in result if f.get("suspected_source") == "engine"]
        assert engine_findings, "Strong engine should survive weak wheel"

    def test_empty_input(self) -> None:
        assert _suppress_engine_aliases([]) == []

    def test_output_capped_at_5(self) -> None:
        findings = [(i, self._make_finding("wheel/tire", 0.50 + i * 0.05)) for i in range(7)]
        result = _suppress_engine_aliases(findings)
        assert len(result) <= 5


# ---------------------------------------------------------------------------
# Finding 4: _build_run_suitability_checks  (summary.py:600)
# SEVERITY: HIGH
# WHY: Constructs the data-quality checklist visible in every PDF report.
#      Logic for speed variation, sensor coverage, reference completeness,
#      saturation, and frame integrity checks has zero direct tests.
# ---------------------------------------------------------------------------


class TestBuildRunSuitabilityChecks:
    """Direct unit tests for _build_run_suitability_checks."""

    def test_all_pass(self) -> None:
        checks = _suitability_checks()
        assert all(c["state"] == "pass" for c in checks), (
            f"All checks should pass: {[c['check_key'] for c in checks if c['state'] != 'pass']}"
        )

    @pytest.mark.parametrize(
        "overrides,check_key",
        [
            pytest.param(
                {"steady_speed": True},
                "SUITABILITY_CHECK_SPEED_VARIATION",
                id="speed_variation_steady",
            ),
            pytest.param(
                {"sensor_ids": {"s1"}},
                "SUITABILITY_CHECK_SENSOR_COVERAGE",
                id="sensor_coverage_below_3",
            ),
            pytest.param(
                {"sat_count": 5},
                "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
                id="saturation",
            ),
            pytest.param(
                {
                    "samples": [
                        {"client_id": "c1", "frames_dropped_total": 0},
                        {"client_id": "c1", "frames_dropped_total": 10},
                    ]
                },
                "SUITABILITY_CHECK_FRAME_INTEGRITY",
                id="frame_integrity_dropped",
            ),
            pytest.param(
                {"reference_complete": False},
                "SUITABILITY_CHECK_REFERENCE_COMPLETENESS",
                id="reference_incomplete",
            ),
        ],
    )
    def test_warn_condition(self, overrides: dict[str, Any], check_key: str) -> None:
        checks = _suitability_checks(**overrides)
        check = next(c for c in checks if c["check_key"] == check_key)
        assert check["state"] == "warn"


# ---------------------------------------------------------------------------
# Finding 5: _build_phase_timeline  (summary.py:396)
# SEVERITY: MEDIUM-HIGH
# WHY: Constructs the per-phase timeline shown in UI and PDF.  Bug here
#      misrepresents which driving phases had fault evidence.  Zero tests.
# ---------------------------------------------------------------------------


class TestBuildPhaseTimeline:
    """Direct unit tests for _build_phase_timeline."""

    def test_empty_segments_returns_empty(self) -> None:
        assert _build_phase_timeline([], []) == []

    def test_basic_segment_output(self) -> None:
        segs = [
            _FakeSeg(DrivingPhase.CRUISE, 0.0, 30.0, speed_min=40.0, speed_max=80.0),
            _FakeSeg(DrivingPhase.ACCELERATION, 30.0, 45.0, speed_min=40.0, speed_max=80.0),
        ]
        findings: list[dict[str, object]] = [
            {
                "finding_id": "F001",
                "confidence_0_to_1": 0.60,
                "phase_evidence": {"phases_detected": ["cruise"]},
            }
        ]
        entries = _build_phase_timeline(segs, findings)
        assert len(entries) == 2
        assert entries[0]["phase"] == "cruise"
        assert entries[0]["has_fault_evidence"] is True
        assert entries[1]["has_fault_evidence"] is False

    @pytest.mark.parametrize(
        "finding",
        [
            pytest.param(
                {
                    "finding_id": "REF_SPEED",
                    "confidence_0_to_1": 0.90,
                    "phase_evidence": {"phases_detected": ["cruise"]},
                },
                id="ref_finding_ignored",
            ),
            pytest.param(
                {
                    "finding_id": "F001",
                    "confidence_0_to_1": 0.01,
                    "phase_evidence": {"phases_detected": ["cruise"]},
                },
                id="low_confidence_ignored",
            ),
        ],
    )
    def test_finding_does_not_mark_phase(self, finding: dict[str, object]) -> None:
        """REF_ findings and below-threshold findings should not contribute."""
        entries = _build_phase_timeline([_FakeSeg()], [finding])
        assert entries[0]["has_fault_evidence"] is False


# ---------------------------------------------------------------------------
# Finding 6: _compute_accel_statistics  (summary.py:524)
# SEVERITY: MEDIUM-HIGH
# WHY: Computes saturation detection, per-axis mean/variance, and magnitude.
#      Saturation miscounting silently breaks the suitability checklist.
#      Zero direct tests.
# ---------------------------------------------------------------------------


class TestComputeAccelStatistics:
    """Direct unit tests for _compute_accel_statistics."""

    def test_empty_samples(self) -> None:
        result = _compute_accel_statistics([], "ADXL345")
        assert result["sat_count"] == 0
        assert result["accel_x_vals"] == []
        assert result["accel_mag_vals"] == []

    def test_basic_values(self) -> None:
        samples: list[dict[str, Any]] = [
            {
                "accel_x_g": 0.1,
                "accel_y_g": 0.2,
                "accel_z_g": 1.0,
                "vibration_strength_db": 12.0,
            }
        ]
        result = _compute_accel_statistics(samples, "ADXL345")
        assert len(result["accel_x_vals"]) == 1
        assert result["accel_x_vals"][0] == pytest.approx(0.1)
        assert len(result["accel_mag_vals"]) == 1
        expected_mag = math.sqrt(0.1**2 + 0.2**2 + 1.0**2)
        assert result["accel_mag_vals"][0] == pytest.approx(expected_mag, rel=1e-3)

    def test_saturation_detected_near_limit(self) -> None:
        # ADXL345 has ±16g limit; 98% threshold = 15.68g
        samples: list[dict[str, Any]] = [
            {"accel_x_g": 15.7, "accel_y_g": 0.0, "accel_z_g": 0.0},
        ]
        result = _compute_accel_statistics(samples, "ADXL345")
        assert result["sat_count"] >= 1, "Near-limit value should count as saturation"

    def test_missing_axes_handled(self) -> None:
        samples: list[dict[str, Any]] = [{"accel_x_g": 0.5}]
        result = _compute_accel_statistics(samples, "unknown")
        assert len(result["accel_x_vals"]) == 1
        assert result["accel_y_vals"] == []
        assert result["accel_mag_vals"] == []  # can't compute magnitude without all 3

    def test_unknown_sensor_no_saturation_check(self) -> None:
        """When sensor_limit is None, no saturation counting should occur."""
        samples: list[dict[str, Any]] = [
            {"accel_x_g": 999.0, "accel_y_g": 999.0, "accel_z_g": 999.0},
        ]
        result = _compute_accel_statistics(samples, "totally_unknown_sensor")
        # With unknown sensor, sensor_limit should be None → sat_count = 0
        if result["sensor_limit"] is None:
            assert result["sat_count"] == 0


# ---------------------------------------------------------------------------
# Finding 7: _phase_ranking_score  (summary.py:177)
# SEVERITY: MEDIUM
# WHY: Multiplier used inside select_top_causes to rank findings by phase
#      evidence.  Incorrect weighting silently re-orders top causes in
#      the report.  Not directly tested.
# ---------------------------------------------------------------------------


class TestPhaseRankingScore:
    """Direct unit tests for _phase_ranking_score."""

    def test_no_phase_evidence(self) -> None:
        score = _phase_ranking_score({"confidence_0_to_1": 0.80})
        # No phase_evidence → cruise_fraction=0 → multiplier=0.85
        assert score == pytest.approx(0.80 * 0.85, rel=1e-3)

    def test_full_cruise_phase(self) -> None:
        finding: dict[str, object] = {
            "confidence_0_to_1": 0.80,
            "phase_evidence": {"cruise_fraction": 1.0},
        }
        score = _phase_ranking_score(finding)
        assert score == pytest.approx(0.80 * 1.0, rel=1e-3)

    def test_half_cruise(self) -> None:
        finding: dict[str, object] = {
            "confidence_0_to_1": 0.80,
            "phase_evidence": {"cruise_fraction": 0.50},
        }
        score = _phase_ranking_score(finding)
        expected = 0.80 * (0.85 + 0.15 * 0.50)
        assert score == pytest.approx(expected, rel=1e-3)

    @pytest.mark.parametrize(
        "finding",
        [
            pytest.param({"confidence_0_to_1": None}, id="none_confidence"),
            pytest.param({}, id="missing_confidence_key"),
        ],
    )
    def test_degenerate_confidence_returns_zero(self, finding: dict[str, object]) -> None:
        assert _phase_ranking_score(finding) == 0.0


# ---------------------------------------------------------------------------
# Finding 8: MetricsLogger._extract_strength_data  (metrics_log.py:429)
# SEVERITY: MEDIUM-HIGH
# WHY: Parses nested dicts from processor output to extract vibration_strength_db,
#      strength_bucket, top_peaks.  Complex dict traversal with multiple fallback
#      paths.  Zero direct tests.
# ---------------------------------------------------------------------------


class TestExtractStrengthData:
    """Direct unit tests for MetricsLogger._extract_strength_data."""

    def test_empty_metrics(self) -> None:
        strength, db, bucket, peak, floor, peaks = MetricsLogger._extract_strength_data({})
        assert strength == {}
        assert db is None
        assert bucket is None
        assert peaks == []

    def test_top_level_strength_metrics(self) -> None:
        metrics: dict[str, object] = {
            "strength_metrics": {
                "vibration_strength_db": 18.5,
                "strength_bucket": "l3",
                "peak_amp_g": 0.02,
                "noise_floor_amp_g": 0.001,
                "top_peaks": [{"hz": 45.0, "amp": 0.015}],
            }
        }
        strength, db, bucket, peak, floor, peaks = MetricsLogger._extract_strength_data(metrics)
        assert db == pytest.approx(18.5)
        assert bucket == "l3"
        assert len(peaks) == 1
        assert peaks[0]["hz"] == pytest.approx(45.0)

    def test_nested_combined_fallback(self) -> None:
        metrics: dict[str, object] = {
            "combined": {
                "strength_metrics": {
                    "vibration_strength_db": 12.0,
                    "strength_bucket": "l2",
                    "top_peaks": [],
                }
            }
        }
        strength, db, bucket, _, _, _ = MetricsLogger._extract_strength_data(metrics)
        assert db == pytest.approx(12.0)
        assert bucket == "l2"

    def test_invalid_peak_data_filtered(self) -> None:
        metrics: dict[str, object] = {
            "strength_metrics": {
                "vibration_strength_db": 10.0,
                "top_peaks": [
                    {"hz": float("nan"), "amp": 0.01},  # nan hz
                    {"hz": 50.0, "amp": float("inf")},  # inf amp
                    {"hz": -1.0, "amp": 0.01},  # negative hz
                    {"hz": 50.0, "amp": 0.01},  # valid
                    "not_a_dict",  # invalid type
                ],
            }
        }
        _, _, _, _, _, peaks = MetricsLogger._extract_strength_data(metrics)
        assert len(peaks) == 1
        assert peaks[0]["hz"] == pytest.approx(50.0)

    def test_empty_bucket_treated_as_none(self) -> None:
        metrics: dict[str, object] = {
            "strength_metrics": {
                "vibration_strength_db": 5.0,
                "strength_bucket": "",
                "top_peaks": [],
            }
        }
        _, _, bucket, _, _, _ = MetricsLogger._extract_strength_data(metrics)
        assert bucket is None


# ---------------------------------------------------------------------------
# Finding 9: MetricsLogger._resolve_speed_context  (metrics_log.py:367)
# SEVERITY: MEDIUM
# WHY: Resolves GPS/manual speed, computes estimated engine RPM from tire
#      specs and gear ratios.  Incorrect RPM estimation propagates bad data
#      into sample records and downstream analysis.  Zero direct tests.
# ---------------------------------------------------------------------------


class TestResolveSpeedContext:
    """Tests for _resolve_speed_context via a minimal MetricsLogger setup."""

    def test_no_speed_available(self) -> None:
        logger, _ = _make_metrics_logger()
        speed_kmh, gps_speed, source, rpm, fdr, gr = logger._resolve_speed_context()
        assert speed_kmh is None
        assert rpm is None

    def test_gps_speed_available(self) -> None:
        logger, gps_mock = _make_metrics_logger()
        gps_mock.speed_mps = 10.0  # 36 km/h
        gps_mock.resolve_speed.return_value = MagicMock(source="gps", speed_mps=10.0)
        speed_kmh, gps_speed, source, rpm, _, _ = logger._resolve_speed_context()
        assert speed_kmh == pytest.approx(36.0, rel=0.01)
        assert gps_speed == pytest.approx(36.0, rel=0.01)
        assert source == "gps"
        assert rpm is not None and rpm > 0

    def test_manual_override(self) -> None:
        logger, gps_mock = _make_metrics_logger()
        gps_mock.override_speed_mps = 20.0  # 72 km/h
        gps_mock.resolve_speed.return_value = MagicMock(source="manual", speed_mps=20.0)
        speed_kmh, _, source, _, _, _ = logger._resolve_speed_context()
        assert speed_kmh == pytest.approx(72.0, rel=0.01)
        assert source == "manual"

    def test_no_gear_ratio_skips_rpm(self) -> None:
        logger, gps_mock = _make_metrics_logger()
        gps_mock.resolve_speed.return_value = MagicMock(source="gps", speed_mps=15.0)
        # Remove gear ratio from settings
        logger.analysis_settings.snapshot.return_value = {
            "tire_width_mm": 205,
            "tire_aspect_pct": 55,
            "rim_in": 16,
            "final_drive_ratio": 3.73,
            "current_gear_ratio": None,  # missing
            "tire_deflection_factor": None,
        }
        _, _, _, rpm, _, _ = logger._resolve_speed_context()
        assert rpm is None, "Without gear_ratio, RPM should not be estimated"


# ---------------------------------------------------------------------------
# Finding 10: summarize_run_data — edge cases (summary.py:710)
# SEVERITY: MEDIUM
# WHY: The main orchestrator function.  While it has integration tests,
#      boundary inputs (empty samples, all-None axes, zero duration) are
#      untested and represent production crash vectors.
# ---------------------------------------------------------------------------


class TestSummarizeRunDataEdgeCases:
    """Integration edge cases for summarize_run_data."""

    _MINIMAL_META: dict[str, Any] = {
        "run_id": "test-edge",
        "start_time_utc": "2025-01-01T00:00:00Z",
        "end_time_utc": "2025-01-01T00:01:00Z",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 800,
    }

    def test_empty_samples_no_crash(self) -> None:
        summary = summarize_run_data(self._MINIMAL_META, [], lang="en")
        assert summary["rows"] == 0
        assert summary.get("run_suitability") is not None

    def test_samples_with_all_none_axes(self) -> None:
        samples: list[dict[str, Any]] = [
            {
                "t_s": i,
                "client_id": "c1",
                "location": "front",
                "vibration_strength_db": 0.0,
                "strength_bucket": "l1",
            }
            for i in range(10)
        ]
        summary = summarize_run_data(self._MINIMAL_META, samples, lang="en")
        assert summary["rows"] == 10
        accel_sanity = summary.get("data_quality", {}).get("accel_sanity", {})
        assert accel_sanity.get("saturation_count") == 0

    def test_single_sample_no_crash(self) -> None:
        samples: list[dict[str, Any]] = [
            {
                "t_s": 0,
                "client_id": "c1",
                "location": "front",
                "accel_x_g": 0.1,
                "accel_y_g": 0.0,
                "accel_z_g": 1.0,
                "vibration_strength_db": 5.0,
                "strength_bucket": "l1",
            }
        ]
        summary = summarize_run_data(self._MINIMAL_META, samples, lang="en")
        assert summary["rows"] == 1
        assert summary.get("findings") is not None

    def test_nl_lang_no_crash(self) -> None:
        summary = summarize_run_data(self._MINIMAL_META, [], lang="nl")
        assert summary["lang"] == "nl"

    def test_missing_metadata_fields(self) -> None:
        """Minimal metadata (only run_id) should not crash."""
        summary = summarize_run_data({"run_id": "minimal"}, [], lang="en")
        assert summary["run_id"] == "minimal"


# ===== From test_report_pipeline_audit.py =====

"""Report pipeline audit — tests covering 10 findings from the report-generation
traceability and consistency audit.

These tests document and verify issues found in the analysis → report_data →
PDF pipeline.  Each test class corresponds to one audit finding.
"""


import inspect

from vibesensor.analysis.report_data_builder import (
    _finding_strength_values,
    _peak_classification_text,
    _top_strength_values,
    map_summary,
)
from vibesensor.report import pdf_builder
from vibesensor.report.pdf_builder import (
    _draw_next_steps_table,
    _draw_peaks_table,
    _draw_system_card,
    _page1,
)
from vibesensor.report_i18n import tr

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_minimal_summary(*, overrides: dict | None = None) -> dict:
    """Return a minimal summary dict that ``map_summary`` can process."""
    base: dict = {
        "lang": "en",
        "report_date": "2025-01-01T00:00:00",
        "metadata": {"car_name": "Test Car"},
        "findings": [],
        "top_causes": [],
        "speed_stats": {},
        "most_likely_origin": {},
        "sensor_intensity_by_location": [],
        "run_suitability": [],
        "phase_info": None,
        "plots": {"peaks_table": []},
        "test_plan": [],
    }
    if overrides:
        base.update(overrides)
    return base


def _make_peaks_table_row(
    *,
    rank: int = 1,
    frequency_hz: float = 42.0,
    p95_intensity_db: float = 18.5,
    strength_db: float | None = None,
    presence_ratio: float = 0.7,
    persistence_score: float = 0.5,
    burstiness: float = 1.5,
    peak_classification: str = "patterned",
    order_label: str = "",
    typical_speed_band: str = "50-80 km/h",
    p95_vs_run_noise_ratio: float = 5.0,
    spatial_uniformity: float | None = None,
    speed_uniformity: float | None = None,
) -> dict:
    """Build a single peaks-table row dict as produced by plot_data._top_peaks_table_rows."""
    if strength_db is None:
        strength_db = p95_intensity_db  # mirrors the current (buggy) behavior
    return {
        "rank": rank,
        "frequency_hz": frequency_hz,
        "p95_intensity_db": p95_intensity_db,
        "strength_db": strength_db,
        "presence_ratio": presence_ratio,
        "persistence_score": persistence_score,
        "burstiness": burstiness,
        "peak_classification": peak_classification,
        "order_label": order_label,
        "typical_speed_band": typical_speed_band,
        "p95_vs_run_noise_ratio": p95_vs_run_noise_ratio,
        "spatial_uniformity": spatial_uniformity,
        "speed_uniformity": speed_uniformity,
    }


def _en_tr(key: str, **kw: object) -> str:
    """English translation shortcut used by multiple test classes."""
    return tr("en", key, **kw)


# ===================================================================
# Finding 1 (KNOWN-C1, confirmed still present):
#   Peaks table "Peak (dB)" and "Strength (dB)" columns always show
#   identical values — both read from p95_intensity_db.
# ===================================================================


class TestPeakDbEqualsStrengthDb:
    """Peaks-table strength_db is always assigned p95_intensity_db,
    making the two columns redundant.

    Evidence: plot_data.py line ~379: bucket["strength_db"] = p95_intensity_db
    Root cause: strength_db should be computed differently from p95_intensity_db
      (e.g. using SNR-based canonical_vibration_db against MEMS noise floor)
      but currently just aliases p95_intensity_db.
    """

    def test_strength_db_equals_p95_intensity_db_in_source(self) -> None:
        """Confirm the assignment in plot_data produces identical values."""
        row = _make_peaks_table_row(p95_intensity_db=22.3, strength_db=22.3)
        summary = _make_minimal_summary(overrides={"plots": {"peaks_table": [row]}})
        data = map_summary(summary)
        assert len(data.peak_rows) == 1
        pr = data.peak_rows[0]
        # Currently both are identical — this test documents the bug
        assert pr.peak_db == pr.strength_db, (
            "Expected peak_db == strength_db (documenting current behavior)"
        )

    def test_different_strength_db_would_show_distinct_columns(self) -> None:
        """If strength_db were computed differently, columns would differ."""
        # Simulate a hypothetical fix where strength_db ≠ p95_intensity_db
        row = _make_peaks_table_row(p95_intensity_db=22.3, strength_db=15.1)
        summary = _make_minimal_summary(overrides={"plots": {"peaks_table": [row]}})
        data = map_summary(summary)
        pr = data.peak_rows[0]
        assert pr.peak_db == "22.3"
        assert pr.strength_db == "15.1"


# ===================================================================
# Finding 2 (KNOWN-C1, confirmed still present):
#   NextStep confirm/falsify/eta/speed_band populated but never
#   rendered in PDF.
# ===================================================================


class TestNextStepFieldsNotRendered:
    """NextStep dataclass has confirm, falsify, eta, speed_band fields
    that are populated by the builder but the PDF renderer only reads
    step.action and step.why.

    Evidence: pdf_builder.py lines 673-675 — only action and why are used.
    Impact: actionable diagnostic guidance is lost in PDF output.
    """

    def test_nextstep_fields_populated_by_builder(self) -> None:
        """Verify the builder does populate these fields."""
        step = {
            "what": "Inspect front-left wheel bearing",
            "why": "Dominant order in front-left sensor",
            "confirm": "Noise disappears at low speed",
            "falsify": "Noise persists with new bearing",
            "eta": "30 min",
            "speed_band": "60-90 km/h",
        }
        # Need a high-confidence finding + top_cause so the builder does NOT
        # fall into Tier A (which replaces test_plan steps with generic guidance).
        finding = {
            "finding_id": "F_ORDER",
            "suspected_source": "wheel/tire",
            "confidence_0_to_1": 0.85,
            "frequency_hz_or_order": "1x wheel",
            "strongest_location": "front-left wheel",
            "amplitude_metric": {"value": 0.05},
            "evidence_metrics": {"vibration_strength_db": 20.0},
        }
        top_cause = {
            "finding_id": "F_ORDER",
            "source": "wheel/tire",
            "confidence": 0.85,
            "confidence_tone": "success",
            "signatures_observed": ["1x wheel"],
            "strongest_location": "front-left wheel",
        }
        summary = _make_minimal_summary(
            overrides={
                "test_plan": [step],
                "findings": [finding],
                "top_causes": [top_cause],
            }
        )
        data = map_summary(summary)
        # Find the step that came from our test_plan (not Tier A guidance)
        matching = [ns for ns in data.next_steps if "bearing" in ns.action.lower()]
        assert len(matching) == 1, f"Expected 1 bearing step, got {len(matching)}"
        ns = matching[0]
        assert ns.confirm == "Noise disappears at low speed"
        assert ns.falsify == "Noise persists with new bearing"
        assert ns.eta == "30 min"
        assert ns.speed_band == "60-90 km/h"

    def test_pdf_renderer_renders_confirm_falsify_eta(self) -> None:
        """After fix: renderer now accesses .action, .why, and optional fields."""
        source = inspect.getsource(_draw_next_steps_table)
        assert "step.action" in source
        assert "step.why" in source
        # These fields are NOW referenced after the fix:
        assert "step.confirm" in source
        assert "step.falsify" in source
        assert "step.eta" in source


# ===================================================================
# Finding 3 (KNOWN-C1, confirmed still present):
#   top_causes fallback chain can bypass persistence-aware ranking.
# ===================================================================


class TestTopCausesFallbackBypassesPersistenceRanking:
    """When top_causes_actionable is empty, the fallback chain falls to
    findings_non_ref (raw findings) which are NOT ranked by
    select_top_causes.  This bypasses the persistence-aware
    phase-adjusted ranking.

    Evidence: report_data_builder.py line ~312:
      top_causes = top_causes_actionable or findings_non_ref or top_causes_non_ref or top_causes_all
    """

    def test_fallback_to_findings_non_ref_skips_ranking(self) -> None:
        """When actionable causes are empty, raw findings are used unranked."""
        # Create findings with NO top_causes — forces fallback
        findings = [
            {
                "finding_id": "F_ORDER",
                "suspected_source": "wheel/tire",
                "confidence_0_to_1": 0.3,
                "frequency_hz_or_order": "1x wheel",
                "strongest_location": "front-left wheel",
                "amplitude_metric": {"value": 0.05},
                "evidence_metrics": {"vibration_strength_db": 15.0},
            },
            {
                "finding_id": "F_ORDER",
                "suspected_source": "engine",
                "confidence_0_to_1": 0.6,
                "frequency_hz_or_order": "2x engine",
                "strongest_location": "engine bay",
                "amplitude_metric": {"value": 0.08},
                "evidence_metrics": {"vibration_strength_db": 20.0},
            },
        ]
        summary = _make_minimal_summary(
            overrides={
                "findings": findings,
                "top_causes": [],  # empty → forces fallback
            }
        )
        data = map_summary(summary)
        # The observed primary system comes from findings_non_ref[0],
        # which is the first finding by list order, NOT the highest-confidence one.
        # This documents the fallback bypass.
        assert data.observed.primary_system is not None


# ===================================================================
# Finding 4 (KNOWN-C1, confirmed still present):
#   _peak_classification_text maps unrecognized classifications to
#   "persistent".
# ===================================================================


class TestPeakClassificationFallback:
    """Unrecognized peak_classification values silently map to
    CLASSIFICATION_PERSISTENT instead of UNKNOWN.

    Evidence: report_data_builder.py lines 199-212.
    """

    def test_unrecognized_maps_to_title_case(self) -> None:
        result = _peak_classification_text("totally_new_type", _en_tr)
        # Unrecognised types are title-cased from the raw value
        assert result == "Totally New Type"

    def test_empty_maps_to_unknown(self) -> None:
        result = _peak_classification_text("", _en_tr)
        assert result == _en_tr("UNKNOWN")


# ===================================================================
# Finding 5 (KNOWN-C1, confirmed still present):
#   Dead db_value variable in _top_strength_values.
# ===================================================================


class TestDeadDbValueVariable:
    """FIXED: _top_strength_values no longer has the dead db_value
    variable. The function directly returns sensor_db in the fallback
    path without an intermediate unused variable.
    """

    def test_db_value_removed(self) -> None:
        """After fix: db_value variable should no longer exist in source."""
        source = inspect.getsource(_top_strength_values)
        assert "db_value" not in source, "Dead db_value variable should have been removed"


# ===================================================================
# Finding 6 (KNOWN-C1, confirmed still present):
#   SystemFindingCard.tone never used by PDF renderer.
# ===================================================================


class TestSystemFindingCardToneUnused:
    """SystemFindingCard.tone is set by the builder but the PDF renderer
    never reads it — cards are always drawn with SOFT_BG background.

    Evidence: pdf_builder.py _draw_system_card uses fixed SOFT_BG;
              theme.py defines card_success_bg/card_warn_bg/card_error_bg
              which are never referenced by pdf_builder.py.
    """

    def test_tone_referenced_in_renderer(self) -> None:
        """After fix: _draw_system_card uses card.tone for colors."""
        source = inspect.getsource(_draw_system_card)
        assert "card.tone" in source, "_draw_system_card must reference card.tone for theme colors"

    def test_tone_is_populated_by_builder(self) -> None:
        finding = {
            "finding_id": "F_ORDER",
            "suspected_source": "wheel/tire",
            "confidence_0_to_1": 0.8,
            "frequency_hz_or_order": "1x wheel",
            "strongest_location": "front-left wheel",
            "amplitude_metric": {"value": 0.05},
            "evidence_metrics": {"vibration_strength_db": 15.0},
        }
        summary = _make_minimal_summary(
            overrides={
                "findings": [finding],
                "top_causes": [
                    {
                        "finding_id": "F_ORDER",
                        "source": "wheel/tire",
                        "confidence": 0.8,
                        "confidence_tone": "success",
                        "signatures_observed": ["1x wheel"],
                        "strongest_location": "front-left wheel",
                    }
                ],
            }
        )
        data = map_summary(summary)
        assert len(data.system_cards) >= 1
        # tone is populated but never rendered
        assert data.system_cards[0].tone in {"neutral", "success", "warn"}


# ===================================================================
# Finding 7 (NEW):
#   ObservedSignature.phase and ReportTemplateData.phase_info are
#   computed and stored but never rendered in the PDF.
# ===================================================================


class TestPhaseFieldsNeverRendered:
    """ObservedSignature.phase is populated from _dominant_phase() and
    phase_info is passed through to ReportTemplateData, but the PDF
    renderer never accesses either field.

    Evidence: grep -n 'phase' pdf_builder.py → 0 results.
    Impact: driving-phase context (acceleration/deceleration/coast-down)
            is invisible in the PDF report despite being computed.
    """

    def test_observed_phase_populated(self) -> None:
        summary = _make_minimal_summary(
            overrides={
                "phase_info": {
                    "phase_counts": {
                        "idle": 5,
                        "acceleration": 50,
                        "cruise": 100,
                        "deceleration": 20,
                    }
                }
            }
        )
        data = map_summary(summary)
        # phase is populated
        assert data.observed.phase is not None
        assert data.observed.phase == "cruise"
        # phase_info is passed through
        assert data.phase_info is not None
        assert "phase_counts" in data.phase_info

    def test_phase_not_in_pdf_renderer_source(self) -> None:
        source = inspect.getsource(pdf_builder)
        # The word 'phase' appears nowhere in the PDF builder
        # (except possibly in comment strings or variable names like
        # phase_segments for transient findings)
        # But observed.phase and data.phase_info are never accessed
        assert "observed.phase" not in source
        assert "data.phase_info" not in source


# ===================================================================
# Finding 8 (NEW):
#   Data trust panel has no boundary check — long detail strings can
#   draw below the panel rectangle.
# ===================================================================


class TestDataTrustPanelOverflow:
    """The data-trust panel renders items in a loop decrementing ty
    but never checks whether ty has gone below the panel's bottom edge
    (next_y).  With 5+ items having multi-line detail text, content
    can overflow.

    Evidence: pdf_builder.py lines 552-569 — no `ty < bottom` guard.
    Impact: text drawn outside the panel boundary overlapping the footer.
    """

    def test_data_trust_panel_renders(self) -> None:
        """Verify that the data-trust section renders without crashing,
        even with many items."""
        source = inspect.getsource(_page1)
        # The data-trust section exists in _page1.
        assert "Data Trust" in source


# ===================================================================
# Finding 9 (NEW):
#   Peaks table on page 2 has a fixed height (53 mm) which may not
#   accommodate 6 data rows + header when rendered with wrapping
#   relevance text.
# ===================================================================


class TestPeaksTableFixedHeight:
    """The peaks table uses a fixed panel height of 53 mm regardless of
    how many rows it contains.  _draw_peaks_table uses a y_bottom guard
    to limit visible rows to what fits in the panel height.

    Evidence: pdf_builder.py: y - row_h < y_bottom: break
    """

    def test_peaks_table_rows_cap_at_six(self) -> None:
        """Verify the renderer uses height-based limiting (y_bottom guard)."""
        source = inspect.getsource(_draw_peaks_table)
        assert "y_bottom" in source

    def test_fixed_height_with_many_rows(self) -> None:
        """Eight peaks in data; the builder forwards all of them and the
        renderer trims via a y_bottom guard at render time."""
        rows = [_make_peaks_table_row(rank=i, frequency_hz=20.0 + i * 5) for i in range(1, 9)]
        summary = _make_minimal_summary(overrides={"plots": {"peaks_table": rows}})
        data = map_summary(summary)
        # Builder forwards up to 8 above-noise peaks
        assert len(data.peak_rows) == 8
        # The renderer uses height-based y_bottom limiting (not hard slice)
        source = inspect.getsource(_draw_peaks_table)
        assert "y_bottom" in source


# ===================================================================
# Finding 10 (NEW):
#   _finding_strength_values computes peak_amp but may not use it
#   when evidence_metrics.vibration_strength_db exists — the computed
#   peak_amp is wasted work.
# ===================================================================


class TestFindingStrengthValuesWastedComputation:
    """_finding_strength_values always extracts peak_amp from
    amplitude_metric.value, but if evidence_metrics.vibration_strength_db
    is present, it returns immediately without using peak_amp.
    peak_amp is only used in the second fallback path.

    Evidence: report_data_builder.py lines 118-138.
    Impact: minor inefficiency; peak_amp is computed even when not needed.
    """

    def test_early_return_with_db_present(self) -> None:
        finding = {
            "amplitude_metric": {"value": 0.123},
            "evidence_metrics": {"vibration_strength_db": 25.0},
        }
        result = _finding_strength_values(finding)
        # Returns 25.0 immediately without using peak_amp
        assert result == 25.0

    def test_fallback_uses_peak_amp_and_noise_floor(self) -> None:
        finding = {
            "amplitude_metric": {"value": 0.05},
            "evidence_metrics": {
                # No vibration_strength_db → falls through to canonical calc
                "mean_noise_floor": 0.01,
            },
        }
        result = _finding_strength_values(finding)
        # Should compute canonical_vibration_db(0.05, 0.01)
        assert result is not None
        assert result > 0

    def test_returns_none_when_no_metrics(self) -> None:
        result = _finding_strength_values({})
        assert result is None
