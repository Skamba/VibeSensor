"""Raw-capture replay helpers for post-stop analysis."""

from __future__ import annotations

import os
from collections import defaultdict, deque
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from math import isfinite
from typing import Literal, cast

import numpy as np
import numpy.typing as npt
from numpy.lib.stride_tricks import as_strided

from vibesensor.common.json_utils import i18n_ref
from vibesensor.domain.strength_metrics import StrengthPeak
from vibesensor.dsp.constants import SPECTRUM_MAX_HZ, SPECTRUM_MIN_HZ
from vibesensor.dsp.fft_analysis import SpectralAnalysisComputer
from vibesensor.dsp.vibration_strength import VibrationStrengthMetrics
from vibesensor.dsp.window_spectrum import WindowSpectrum
from vibesensor.recording.raw_capture import RawCaptureSensorData, RawRunCapture
from vibesensor.recording.raw_capture_quality import (
    RawCaptureLossPolicyAssessment,
    assess_raw_capture_loss_policy,
)
from vibesensor.recording.raw_capture_timeline import (
    RawSensorTimeline,
    RawWindowSegment,
    assemble_raw_window_samples,
    build_raw_sensor_timeline,
    contiguous_raw_window_starts,
    raw_timeline_has_unverified_sync,
    raw_timeline_is_legacy,
    resolve_raw_window_end_time,
)
from vibesensor.recording.run_schema import RunMetadata
from vibesensor.recording.sensor_frame import SensorFrame
from vibesensor.summary.run_context_warning import (
    WARNING_CODE_RAW_CAPTURE_LOSS_POLICY,
    WARNING_CODE_RAW_REPLAY_COVERAGE_INCOMPLETE,
    WARNING_CODE_RAW_REPLAY_DROPPED_CHUNKS,
    WARNING_CODE_RAW_REPLAY_FFT_UNUSABLE,
    WARNING_CODE_RAW_REPLAY_LEGACY_FALLBACK,
    WARNING_CODE_RAW_REPLAY_SYNC_UNVERIFIED,
    WARNING_CODE_RAW_REPLAY_TIMING_FALLBACK,
    RunContextWarning,
)

__all__ = [
    "RawReplayResult",
    "RawReplaySummary",
    "RawReplayWindowCoverage",
    "build_raw_backed_samples",
]

type RawReplayCoverageState = Literal["complete", "partial", "missing"]
type RawReplayConfidence = Literal["full", "partial", "fallback", "unavailable"]
type RawCaptureMode = Literal["raw_backed", "partial_raw_backed", "summary_only"]

# Raw windows whose strengths are taken together: enough to share the per-call
# cost of the strength pipeline, few enough to hold little memory.
_WINDOWS_PER_BATCH = 128
# Raw windows whose spectra the replay's FFT thread computes at once
# (``combined_spectra``). On the Pi 3 A+ larger chunks, or more threads,
# gain nothing and hold more memory (docs/multithreading_performance.md).
_WINDOWS_PER_FFT = 64
# The most a chunk's windows may span, as the bytes of the strided view of
# every window there, to be gathered in one step: well within what numpy
# allows a view on a 32-bit system (the Pi's).
_MAX_GATHER_VIEW_BYTES = 1 << 30
# Threads computing the spectra, and chunks queued for them: enough to keep
# them busy.
# EXPERIMENT (free-threaded CPython): VS_EXP_THREADS threads compute spectra and
# strengths when above 1.
_EXP_THREADS = int(os.environ.get("VS_EXP_THREADS", "1"))
_FFT_WORKERS = max(1, _EXP_THREADS)
_FFT_CHUNKS_AHEAD = 2 * _FFT_WORKERS


@dataclass(frozen=True, slots=True)
class RawReplayWindowCoverage:
    """Per-window replay coverage classification for one persisted summary sample."""

    client_id: str
    t_s: float | None
    coverage_state: RawReplayCoverageState
    raw_backed: bool
    reason: str | None = None
    # The window's mean reading per axis (its 0 Hz part: gravity and the car's
    # own acceleration), in g (counts when the run has no scale); None without
    # a complete raw window.
    mean_xyz: tuple[float, float, float] | None = None


@dataclass(frozen=True, slots=True)
class RawReplaySummary:
    """Rolled-up replay coverage facts persisted into analysis metadata."""

    raw_capture_available: bool
    raw_backed_summary_row_count: int
    replay_window_count: int
    complete_window_count: int
    partial_window_count: int
    missing_window_count: int
    gap_count: int
    overlap_count: int
    dropped_chunk_count: int
    late_packet_chunk_count: int
    queue_overflow_chunk_count: int
    invalid_chunk_count: int
    write_error_chunk_count: int
    timing_fallback_count: int
    sample_rate_mismatch_count: int
    fft_unusable_window_count: int
    sample_rate_unverified_sensor_count: int
    unanchored_sensor_count: int
    legacy_sensor_count: int
    sync_unverified_sensor_count: int
    stale_sync_sensor_count: int
    high_rtt_sensor_count: int
    timing_unreliable_sensor_count: int
    replay_confidence: RawReplayConfidence
    raw_capture_mode: RawCaptureMode
    raw_capture_loss_policy_severity: str = "ok"
    raw_capture_loss_policy_reason: str = "raw_capture_loss_ok"
    raw_capture_loss_policy_max_sensor_drop_ratio: float = 0.0
    raw_capture_loss_policy_max_events_per_minute: float = 0.0
    udp_ingest_queue_drop_count: int = 0
    warnings: tuple[RunContextWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class RawReplayResult:
    """Replay result carrying rebuilt samples plus structured coverage metadata."""

    samples: tuple[SensorFrame, ...]
    summary: RawReplaySummary
    window_coverages: tuple[RawReplayWindowCoverage, ...] = ()


@dataclass(frozen=True, slots=True)
class _ResolvedWindow:
    coverage_state: RawReplayCoverageState
    reason: str | None
    segments: tuple[RawWindowSegment, ...] = ()
    timing_source: str = "explicit_window"


@dataclass(frozen=True, slots=True)
class _WindowRequest:
    """A sample whose raw window is looked for, and when that window ends."""

    sample: SensorFrame
    sample_rate_hz: int
    # On the sensor's clock (``_requested_end_us``); None without a sample time.
    requested_end_us: float | None
    # The coverage reason the window has when complete.
    reason: str | None


@dataclass(frozen=True, slots=True)
class _RawWindow:
    """A complete raw window, its spectrum still to be computed.

    Where its samples start in the sensor's raw buffer, or (-1) the ``(N, 3)``
    counts assembled from its segments where they do not follow on there.
    """

    request: _WindowRequest
    raw_start: int
    samples_i16: npt.NDArray[np.int16] | None = None


@dataclass(frozen=True, slots=True)
class _WindowSpectra:
    """Each window's spectrum as a row (``None``: no analysis bins), its last and mean reading."""

    spectra: npt.NDArray[np.float32] | None
    last_xyz: list[tuple[float, float, float]]
    mean_xyz: list[tuple[float, float, float]]


@dataclass(frozen=True, slots=True)
class _PendingWindow:
    """A complete raw window's spectrum, its strength still to be taken (``_rebuilt_samples``)."""

    request: _WindowRequest
    spectrum: WindowSpectrum
    last_xyz: tuple[float, float, float]
    mean_xyz: tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class _ReplayBuildContext:
    fft_n: int
    timelines: dict[str, RawSensorTimeline]
    fft_computer: SpectralAnalysisComputer
    accel_scale_g_per_lsb: float | None


@dataclass(frozen=True, slots=True)
class _ReplayWindowBuildResult:
    samples: tuple[SensorFrame, ...]
    coverages: tuple[RawReplayWindowCoverage, ...]
    raw_backed_count: int
    complete_window_count: int
    partial_window_count: int
    missing_window_count: int
    sample_rate_mismatch_count: int
    timing_fallback_count: int
    fft_unusable_window_count: int


@dataclass(frozen=True, slots=True)
class _RawTimelineSummary:
    gap_count: int
    overlap_count: int
    sample_rate_unverified_sensor_count: int
    unanchored_sensor_count: int
    legacy_sensor_count: int
    sync_unverified_sensor_count: int
    stale_sync_sensor_count: int
    high_rtt_sensor_count: int
    timing_unreliable_sensor_count: int


@dataclass(frozen=True, slots=True)
class _RawCaptureLossCounts:
    dropped_chunk_count: int
    late_packet_chunk_count: int
    queue_overflow_chunk_count: int
    invalid_chunk_count: int
    write_error_chunk_count: int
    udp_ingest_queue_drop_count: int


def build_raw_backed_samples(
    *,
    samples: tuple[SensorFrame, ...],
    metadata: RunMetadata,
    raw_capture: RawRunCapture | None,
) -> RawReplayResult:
    """Replace summary strength metrics with raw-backed metrics when possible."""

    if raw_capture is None:
        return _build_raw_capture_unavailable_replay_result(samples)
    fft_n = int(metadata.fft_window_size_samples or 0)
    if fft_n <= 0:
        return _build_fft_unavailable_replay_result(samples=samples, raw_capture=raw_capture)
    context = _build_replay_context(
        metadata=metadata,
        raw_capture=raw_capture,
        fft_n=fft_n,
    )
    windows = _build_replay_windows(
        samples=samples,
        raw_capture=raw_capture,
        context=context,
    )
    timeline_summary = _summarize_raw_timelines(
        raw_capture=raw_capture,
        timelines=context.timelines,
    )
    loss_counts = _summarize_raw_capture_losses(raw_capture)
    loss_policy = assess_raw_capture_loss_policy(raw_capture.manifest)
    replay_confidence = _replay_confidence(
        raw_backed_summary_row_count=windows.raw_backed_count,
        replay_window_count=len(samples),
        partial_window_count=windows.partial_window_count,
        missing_window_count=windows.missing_window_count,
        gap_count=timeline_summary.gap_count,
        overlap_count=timeline_summary.overlap_count,
        dropped_chunk_count=loss_counts.dropped_chunk_count,
        late_packet_chunk_count=loss_counts.late_packet_chunk_count,
        sample_rate_mismatch_count=windows.sample_rate_mismatch_count,
        fft_unusable_window_count=windows.fft_unusable_window_count,
        sample_rate_unverified_sensor_count=(timeline_summary.sample_rate_unverified_sensor_count),
        unanchored_sensor_count=timeline_summary.unanchored_sensor_count,
        sync_unverified_sensor_count=timeline_summary.sync_unverified_sensor_count,
    )
    return _assemble_raw_replay_result(
        windows=windows,
        timeline_summary=timeline_summary,
        loss_counts=loss_counts,
        loss_policy=loss_policy,
        replay_window_count=len(samples),
        replay_confidence=replay_confidence,
        raw_capture_mode=_raw_capture_mode(
            raw_backed_count=windows.raw_backed_count,
            replay_confidence=replay_confidence,
        ),
    )


def _assemble_raw_replay_result(
    *,
    windows: _ReplayWindowBuildResult,
    timeline_summary: _RawTimelineSummary,
    loss_counts: _RawCaptureLossCounts,
    loss_policy: RawCaptureLossPolicyAssessment,
    replay_window_count: int,
    replay_confidence: RawReplayConfidence,
    raw_capture_mode: RawCaptureMode,
) -> RawReplayResult:
    return RawReplayResult(
        samples=windows.samples,
        summary=RawReplaySummary(
            raw_capture_available=True,
            raw_backed_summary_row_count=windows.raw_backed_count,
            replay_window_count=replay_window_count,
            complete_window_count=windows.complete_window_count,
            partial_window_count=windows.partial_window_count,
            missing_window_count=windows.missing_window_count,
            gap_count=timeline_summary.gap_count,
            overlap_count=timeline_summary.overlap_count,
            dropped_chunk_count=loss_counts.dropped_chunk_count,
            late_packet_chunk_count=loss_counts.late_packet_chunk_count,
            queue_overflow_chunk_count=loss_counts.queue_overflow_chunk_count,
            invalid_chunk_count=loss_counts.invalid_chunk_count,
            write_error_chunk_count=loss_counts.write_error_chunk_count,
            timing_fallback_count=windows.timing_fallback_count,
            sample_rate_mismatch_count=windows.sample_rate_mismatch_count,
            fft_unusable_window_count=windows.fft_unusable_window_count,
            sample_rate_unverified_sensor_count=(
                timeline_summary.sample_rate_unverified_sensor_count
            ),
            unanchored_sensor_count=timeline_summary.unanchored_sensor_count,
            legacy_sensor_count=timeline_summary.legacy_sensor_count,
            sync_unverified_sensor_count=timeline_summary.sync_unverified_sensor_count,
            stale_sync_sensor_count=timeline_summary.stale_sync_sensor_count,
            high_rtt_sensor_count=timeline_summary.high_rtt_sensor_count,
            timing_unreliable_sensor_count=timeline_summary.timing_unreliable_sensor_count,
            replay_confidence=replay_confidence,
            raw_capture_mode=raw_capture_mode,
            raw_capture_loss_policy_severity=loss_policy.severity,
            raw_capture_loss_policy_reason=loss_policy.reason,
            raw_capture_loss_policy_max_sensor_drop_ratio=(loss_policy.max_sensor_drop_ratio),
            raw_capture_loss_policy_max_events_per_minute=(
                loss_policy.max_sensor_loss_events_per_minute
            ),
            udp_ingest_queue_drop_count=loss_counts.udp_ingest_queue_drop_count,
            warnings=_build_replay_warnings(
                raw_backed_summary_row_count=windows.raw_backed_count,
                timing_fallback_count=windows.timing_fallback_count,
                partial_window_count=windows.partial_window_count,
                missing_window_count=windows.missing_window_count,
                gap_count=timeline_summary.gap_count,
                overlap_count=timeline_summary.overlap_count,
                dropped_chunk_count=loss_counts.dropped_chunk_count,
                late_packet_chunk_count=loss_counts.late_packet_chunk_count,
                udp_ingest_queue_drop_count=loss_counts.udp_ingest_queue_drop_count,
                queue_overflow_chunk_count=loss_counts.queue_overflow_chunk_count,
                invalid_chunk_count=loss_counts.invalid_chunk_count,
                write_error_chunk_count=loss_counts.write_error_chunk_count,
                sample_rate_mismatch_count=windows.sample_rate_mismatch_count,
                fft_unusable_window_count=windows.fft_unusable_window_count,
                sample_rate_unverified_sensor_count=(
                    timeline_summary.sample_rate_unverified_sensor_count
                ),
                legacy_sensor_count=timeline_summary.legacy_sensor_count,
                unanchored_sensor_count=timeline_summary.unanchored_sensor_count,
                sync_unverified_sensor_count=timeline_summary.sync_unverified_sensor_count,
                stale_sync_sensor_count=timeline_summary.stale_sync_sensor_count,
                high_rtt_sensor_count=timeline_summary.high_rtt_sensor_count,
                timing_unreliable_sensor_count=timeline_summary.timing_unreliable_sensor_count,
                loss_policy=loss_policy,
            ),
        ),
        window_coverages=windows.coverages,
    )


def _window_request(
    *,
    sample: SensorFrame,
    timeline: RawSensorTimeline | None,
    sensor_data: RawCaptureSensorData | None,
) -> tuple[SensorFrame, RawReplayWindowCoverage] | _WindowRequest:
    """When *sample*'s raw window ends, or the sample as it is with why it has none."""
    if timeline is None or sensor_data is None:
        return _uncovered(sample, "missing", "sensor_missing")
    sensor_manifest = sensor_data.manifest
    sample_rate_hz = int(sensor_manifest.sample_rate_hz or timeline.sample_rate_hz or 0)
    if sample_rate_hz <= 0:
        return _uncovered(sample, "missing", "sample_rate_missing")
    requested_sample_rate_hz = int(sample.sample_rate_hz or 0)
    sample_rate_mismatch = (
        requested_sample_rate_hz > 0 and requested_sample_rate_hz != sample_rate_hz
    )
    if sample_rate_mismatch and sensor_manifest.sample_rate_unverified:
        return _uncovered(sample, "missing", "sample_rate_mismatch")
    requested_end_us, timing_source = _requested_end_us(timeline=timeline, sample=sample)
    return _WindowRequest(
        sample=sample,
        sample_rate_hz=sample_rate_hz,
        requested_end_us=requested_end_us,
        reason=(
            "sample_rate_mismatch"
            if sample_rate_mismatch
            else ("timing_fallback" if timing_source == "legacy_t_s" else None)
        ),
    )


def _uncovered(
    sample: SensorFrame, coverage_state: RawReplayCoverageState, reason: str | None
) -> tuple[SensorFrame, RawReplayWindowCoverage]:
    """*sample* as it is, without a complete raw window, and why."""
    return (
        sample,
        RawReplayWindowCoverage(
            client_id=sample.client_id,
            t_s=sample.t_s,
            coverage_state=coverage_state,
            raw_backed=False,
            reason=reason,
        ),
    )


def _segmented_window(
    *,
    request: _WindowRequest,
    timeline: RawSensorTimeline,
    sensor_data: RawCaptureSensorData,
    fft_n: int,
) -> tuple[SensorFrame, RawReplayWindowCoverage] | _RawWindow:
    """*request*'s window, one resolved on its own: incomplete, or in pieces in the raw buffer."""
    sample = request.sample
    window = _resolve_window(timeline=timeline, sample=sample, fft_n=fft_n)
    if window.coverage_state != "complete" or not window.segments:
        coverage_reason = (
            "timing_fallback" if window.timing_source == "legacy_t_s" else window.reason
        )
        return _uncovered(sample, window.coverage_state, coverage_reason)
    window_i16 = assemble_raw_window_samples(sensor_data=sensor_data, segments=window.segments)
    if window_i16.shape[0] != fft_n:
        return _uncovered(sample, "partial", "window_truncated")
    return _RawWindow(request=request, raw_start=-1, samples_i16=window_i16)


def _window_spectra(
    windows: Sequence[_RawWindow],
    sensor_data: RawCaptureSensorData,
    fft_computer: SpectralAnalysisComputer,
    fft_n: int,
    accel_scale_g_per_lsb: float | None,
) -> _WindowSpectra:
    """The spectra of one sensor's raw *windows*, all at once (``combined_spectra``).

    Each window is laid out as the live tick's FFT block, three axes each
    contiguous, so each spectrum is the one the live tick computes for it.
    """
    # Always _WINDOWS_PER_FFT blocks, a short chunk's last ones zero: every
    # chunk goes through the one FFT plan, rather than one more held per size.
    padded = np.zeros((max(len(windows), _WINDOWS_PER_FFT), 3, fft_n), dtype=np.float32)
    blocks = padded[: len(windows)]
    raw_samples = sensor_data.samples_i16
    # Counts to g as the live tick has them, in one step: int16 to float32 is
    # exact, then the same float32 product.
    scale = (
        np.float32(accel_scale_g_per_lsb)
        if accel_scale_g_per_lsb is not None and accel_scale_g_per_lsb > 0
        else None
    )
    raw_starts = [window.raw_start for window in windows]
    first = min(raw_starts)
    span = max(raw_starts) - first + 1
    if first >= 0 and span * 3 * fft_n * raw_samples.itemsize <= _MAX_GATHER_VIEW_BYTES:
        # One slice of the raw buffer each, gathered in one step (each step
        # this thread takes waits for the GIL while the replay runs Python).
        counts = as_strided(
            raw_samples[first:],
            shape=(span, 3, fft_n),
            strides=(raw_samples.strides[0], raw_samples.strides[1], raw_samples.strides[0]),
            writeable=False,
        )[np.array(raw_starts, dtype=np.intp) - first]
        if scale is None:
            blocks[...] = counts
        else:
            np.multiply(counts, scale, out=blocks)
    else:
        for block, window in zip(blocks, windows, strict=True):
            window_counts = (
                raw_samples[window.raw_start : window.raw_start + fft_n].T
                if window.samples_i16 is None
                else window.samples_i16.T
            )
            if scale is None:
                block[...] = window_counts
            else:
                np.multiply(window_counts, scale, out=block)
    last_xyz = [tuple(last) for last in blocks[:, :, -1].tolist()]
    means = np.mean(padded, axis=2, keepdims=True)
    mean_xyz = [tuple(mean) for mean in means[: len(windows), :, 0].tolist()]
    spectra = fft_computer.combined_spectra(padded, windows[0].request.sample_rate_hz, means=means)
    if spectra is not None:
        spectra = spectra[: len(windows)]
    return _WindowSpectra(
        spectra=spectra,
        last_xyz=cast("list[tuple[float, float, float]]", last_xyz),
        mean_xyz=cast("list[tuple[float, float, float]]", mean_xyz),
    )


def _fft_unusable_window(
    window: _RawWindow,
    last_xyz: tuple[float, float, float],
    mean_xyz: tuple[float, float, float],
) -> tuple[SensorFrame, RawReplayWindowCoverage]:
    """*window*'s sample where its sample rate leaves the spectrum no analysis bins."""
    sample = window.request.sample
    return (
        replace(
            sample,
            accel_x_g=last_xyz[0],
            accel_y_g=last_xyz[1],
            accel_z_g=last_xyz[2],
            dominant_freq_hz=None,
            top_peaks=(),
            vibration_strength_db=None,
            strength_bucket=None,
            strength_peak_amp_g=None,
            strength_floor_amp_g=None,
        ),
        RawReplayWindowCoverage(
            client_id=sample.client_id,
            t_s=sample.t_s,
            coverage_state="complete",
            raw_backed=False,
            reason="fft_no_valid_bins",
            mean_xyz=mean_xyz,
        ),
    )


def _finish_window(
    window: _PendingWindow, strength_metrics: VibrationStrengthMetrics
) -> tuple[SensorFrame, RawReplayWindowCoverage]:
    """*window*'s sample rebuilt from its raw window's spectrum and *strength_metrics*.

    The metrics as ``strength_metrics_from_mapping`` takes them, read directly:
    they are this replay's own, of known types.
    """
    sample, last_xyz = window.request.sample, window.last_xyz
    peaks = strength_metrics["top_peaks"]
    top_peaks = tuple(
        StrengthPeak(
            hz=peak["hz"],
            amp=peak["amp"],
            vibration_strength_db=_finite_or_none(peak["vibration_strength_db"]),
            strength_bucket=peak["strength_bucket"] or None,
            local_floor_amp_g=_finite_or_none(peak.get("local_floor_amp_g")),
        )
        for peak in peaks
        if isfinite(peak["hz"]) and isfinite(peak["amp"]) and peak["hz"] > 0 and peak["amp"] > 0
    )
    dominant_hz = peaks[0]["hz"] if peaks else None
    return (
        replace(
            sample,
            accel_x_g=last_xyz[0],
            accel_y_g=last_xyz[1],
            accel_z_g=last_xyz[2],
            dominant_freq_hz=(
                dominant_hz
                if dominant_hz is not None and isfinite(dominant_hz) and dominant_hz > 0
                else None
            ),
            top_peaks=top_peaks,
            vibration_strength_db=_finite_or_none(strength_metrics["vibration_strength_db"]),
            strength_bucket=strength_metrics["strength_bucket"] or None,
            strength_peak_amp_g=_finite_or_none(strength_metrics["peak_amp_g"]),
            strength_floor_amp_g=_finite_or_none(strength_metrics["noise_floor_amp_g"]),
            spectrum=window.spectrum,
        ),
        RawReplayWindowCoverage(
            client_id=sample.client_id,
            t_s=sample.t_s,
            coverage_state="complete",
            raw_backed=True,
            reason=window.request.reason,
            mean_xyz=window.mean_xyz,
        ),
    )


def _finite_or_none(value: float | None) -> float | None:
    return value if value is not None and isfinite(value) else None


def _raw_capture_mode(
    *,
    raw_backed_count: int,
    replay_confidence: RawReplayConfidence,
) -> RawCaptureMode:
    if raw_backed_count <= 0:
        return "summary_only"
    if replay_confidence == "full":
        return "raw_backed"
    return "partial_raw_backed"


def _build_raw_capture_unavailable_replay_result(
    samples: tuple[SensorFrame, ...],
) -> RawReplayResult:
    return RawReplayResult(
        samples=samples,
        summary=RawReplaySummary(
            raw_capture_available=False,
            raw_backed_summary_row_count=0,
            replay_window_count=len(samples),
            complete_window_count=0,
            partial_window_count=0,
            missing_window_count=len(samples),
            gap_count=0,
            overlap_count=0,
            dropped_chunk_count=0,
            late_packet_chunk_count=0,
            queue_overflow_chunk_count=0,
            invalid_chunk_count=0,
            write_error_chunk_count=0,
            timing_fallback_count=0,
            sample_rate_mismatch_count=0,
            fft_unusable_window_count=0,
            sample_rate_unverified_sensor_count=0,
            unanchored_sensor_count=0,
            legacy_sensor_count=0,
            sync_unverified_sensor_count=0,
            stale_sync_sensor_count=0,
            high_rtt_sensor_count=0,
            timing_unreliable_sensor_count=0,
            replay_confidence="unavailable",
            raw_capture_mode="summary_only",
            udp_ingest_queue_drop_count=0,
        ),
        window_coverages=tuple(
            RawReplayWindowCoverage(
                client_id=sample.client_id,
                t_s=sample.t_s,
                coverage_state="missing",
                raw_backed=False,
                reason="raw_capture_unavailable",
            )
            for sample in samples
        ),
    )


def _build_replay_context(
    *,
    metadata: RunMetadata,
    raw_capture: RawRunCapture,
    fft_n: int,
) -> _ReplayBuildContext:
    timelines = {
        sensor.manifest.client_id: build_raw_sensor_timeline(
            raw_capture, sensor_id=sensor.manifest.client_id
        )
        for sensor in raw_capture.sensors
    }
    return _ReplayBuildContext(
        fft_n=fft_n,
        timelines=timelines,
        fft_computer=SpectralAnalysisComputer(
            fft_n=fft_n,
            spectrum_min_hz=SPECTRUM_MIN_HZ,
            spectrum_max_hz=SPECTRUM_MAX_HZ,
        ),
        accel_scale_g_per_lsb=metadata.accel_scale_g_per_lsb,
    )


def _build_replay_windows(
    *,
    samples: tuple[SensorFrame, ...],
    raw_capture: RawRunCapture,
    context: _ReplayBuildContext,
) -> _ReplayWindowBuildResult:
    replayed, coverages = _rebuilt_samples(
        samples=samples, raw_capture=raw_capture, context=context
    )
    raw_backed_count = 0
    complete_window_count = 0
    partial_window_count = 0
    missing_window_count = 0
    sample_rate_mismatch_count = 0
    timing_fallback_count = 0
    fft_unusable_window_count = 0
    for coverage in coverages:
        if coverage.raw_backed:
            raw_backed_count += 1
        if coverage.coverage_state == "complete":
            complete_window_count += 1
        elif coverage.coverage_state == "partial":
            partial_window_count += 1
        else:
            missing_window_count += 1
        if coverage.reason == "sample_rate_mismatch":
            sample_rate_mismatch_count += 1
        if coverage.reason == "timing_fallback":
            timing_fallback_count += 1
        if coverage.reason == "fft_no_valid_bins":
            fft_unusable_window_count += 1
    return _ReplayWindowBuildResult(
        samples=tuple(replayed),
        coverages=tuple(coverages),
        raw_backed_count=raw_backed_count,
        complete_window_count=complete_window_count,
        partial_window_count=partial_window_count,
        missing_window_count=missing_window_count,
        sample_rate_mismatch_count=sample_rate_mismatch_count,
        timing_fallback_count=timing_fallback_count,
        fft_unusable_window_count=fft_unusable_window_count,
    )


def _rebuilt_samples(
    *,
    samples: tuple[SensorFrame, ...],
    raw_capture: RawRunCapture,
    context: _ReplayBuildContext,
) -> tuple[list[SensorFrame], list[RawReplayWindowCoverage]]:
    """Each sample rebuilt from its raw window, and its window's coverage, in order.

    Sensor by sensor, the windows are found in the raw capture all at once
    (``contiguous_raw_window_starts``; one at a time only where a window is
    incomplete or in pieces). Their spectra are computed ``_WINDOWS_PER_FFT``
    at a time on one FFT thread (``combined_spectra``, most of whose work runs
    with the GIL released), while this thread takes the finished spectra's
    strengths ``_WINDOWS_PER_BATCH`` at a time. Each result is the one the
    window has on its own.
    """
    frames = list(samples)
    coverages: list[RawReplayWindowCoverage | None] = [None] * len(samples)
    # Each sample rate's spectra, kept together as the rows of one array
    # (``WindowSpectrum.rows``), and how many rows are filled. Rows are taken
    # in turn, so only those filled take up memory.
    kept: dict[int, tuple[npt.NDArray[np.float32], list[int]]] = {}
    pending: dict[int, list[tuple[int, _PendingWindow]]] = defaultdict(list)
    in_flight: deque[tuple[list[tuple[int, _RawWindow]], Future[_WindowSpectra]]] = deque()

    finishing: list[Future[None]] = []
    finish_pool = (
        ThreadPoolExecutor(max_workers=_EXP_THREADS, thread_name_prefix="raw-replay-strength")
        if _EXP_THREADS > 1
        else None
    )

    def finish_now(windows: list[tuple[int, _PendingWindow]], sample_rate_hz: int) -> None:
        strength_metrics = context.fft_computer.combined_strength_metrics(
            [window.spectrum for _index, window in windows], sample_rate_hz
        )
        for (index, window), window_metrics in zip(windows, strength_metrics, strict=True):
            frames[index], coverages[index] = _finish_window(window, window_metrics)

    def finish(windows: list[tuple[int, _PendingWindow]], sample_rate_hz: int) -> None:
        if finish_pool is None:
            finish_now(windows, sample_rate_hz)
        else:
            finishing.append(finish_pool.submit(finish_now, list(windows), sample_rate_hz))
        windows.clear()

    def take_oldest() -> None:
        chunk, future = in_flight.popleft()
        computed = future.result()
        sample_rate_hz = chunk[0][1].request.sample_rate_hz
        freq_hz = context.fft_computer.freq_slice(sample_rate_hz)
        if computed.spectra is not None:
            rows, filled = kept.setdefault(
                sample_rate_hz,
                (np.empty((len(samples), freq_hz.size), dtype=np.float32), [0]),
            )
            first = filled[0]
            rows[first : first + len(chunk)] = computed.spectra
            filled[0] += len(chunk)
        windows = pending[sample_rate_hz]
        for position, (index, window) in enumerate(chunk):
            last_xyz, mean_xyz = computed.last_xyz[position], computed.mean_xyz[position]
            if computed.spectra is None:
                frames[index], coverages[index] = _fft_unusable_window(window, last_xyz, mean_xyz)
                continue
            windows.append(
                (
                    index,
                    _PendingWindow(
                        request=window.request,
                        spectrum=WindowSpectrum(
                            freq_hz=freq_hz,
                            amp_g=rows[first + position],
                            rows=rows,
                            row=first + position,
                        ),
                        last_xyz=last_xyz,
                        mean_xyz=mean_xyz,
                    ),
                )
            )
            if len(windows) >= _WINDOWS_PER_BATCH:
                finish(windows, sample_rate_hz)

    requests: dict[str, list[tuple[int, _WindowRequest]]] = defaultdict(list)
    for index, sample in enumerate(samples):
        request = _window_request(
            sample=sample,
            timeline=context.timelines.get(sample.client_id),
            sensor_data=raw_capture.sensor_data(sample.client_id),
        )
        if isinstance(request, _WindowRequest):
            requests[sample.client_id].append((index, request))
        else:
            frames[index], coverages[index] = request

    with ThreadPoolExecutor(max_workers=_FFT_WORKERS, thread_name_prefix="raw-replay-fft") as pool:

        def submit(chunk: list[tuple[int, _RawWindow]], sensor_data: RawCaptureSensorData) -> None:
            in_flight.append(
                (
                    chunk,
                    pool.submit(
                        _window_spectra,
                        [window for _index, window in chunk],
                        sensor_data,
                        context.fft_computer,
                        context.fft_n,
                        context.accel_scale_g_per_lsb,
                    ),
                )
            )
            while len(in_flight) > _FFT_CHUNKS_AHEAD:
                take_oldest()

        for client_id, sensor_requests in requests.items():
            timeline = context.timelines[client_id]
            sensor_data = cast("RawCaptureSensorData", raw_capture.sensor_data(client_id))
            raw_starts = contiguous_raw_window_starts(
                timeline=timeline,
                requested_end_us=np.array(
                    [
                        np.nan if request.requested_end_us is None else request.requested_end_us
                        for _index, request in sensor_requests
                    ],
                    dtype=np.float64,
                ),
                sample_count=context.fft_n,
            )
            chunk: list[tuple[int, _RawWindow]] = []
            for (index, request), raw_start in zip(
                sensor_requests, raw_starts.tolist(), strict=True
            ):
                window = (
                    _RawWindow(request=request, raw_start=raw_start)
                    if raw_start >= 0
                    else _segmented_window(
                        request=request,
                        timeline=timeline,
                        sensor_data=sensor_data,
                        fft_n=context.fft_n,
                    )
                )
                if not isinstance(window, _RawWindow):
                    frames[index], coverages[index] = window
                    continue
                chunk.append((index, window))
                if len(chunk) >= _WINDOWS_PER_FFT:
                    submit(chunk, sensor_data)
                    chunk = []
            if chunk:
                submit(chunk, sensor_data)
        while in_flight:
            take_oldest()
    for sample_rate_hz, windows in pending.items():
        if windows:
            finish(windows, sample_rate_hz)
    for done in finishing:
        done.result()
    if finish_pool is not None:
        finish_pool.shutdown()
    # Every sample has its coverage by now.
    return frames, cast("list[RawReplayWindowCoverage]", coverages)


def _summarize_raw_timelines(
    *,
    raw_capture: RawRunCapture,
    timelines: dict[str, RawSensorTimeline],
) -> _RawTimelineSummary:
    return _RawTimelineSummary(
        gap_count=sum(len(timeline.gap_intervals) for timeline in timelines.values()),
        overlap_count=sum(len(timeline.overlap_intervals) for timeline in timelines.values()),
        sample_rate_unverified_sensor_count=sum(
            1 for sensor in raw_capture.sensors if sensor.manifest.sample_rate_unverified
        ),
        unanchored_sensor_count=sum(1 for timeline in timelines.values() if not timeline.anchored),
        legacy_sensor_count=sum(
            1 for timeline in timelines.values() if raw_timeline_is_legacy(timeline)
        ),
        sync_unverified_sensor_count=sum(
            1 for timeline in timelines.values() if raw_timeline_has_unverified_sync(timeline)
        ),
        stale_sync_sensor_count=sum(
            1
            for timeline in timelines.values()
            if timeline.clock_sync is not None and timeline.clock_sync.proof_state == "stale_sync"
        ),
        high_rtt_sensor_count=sum(
            1
            for timeline in timelines.values()
            if timeline.clock_sync is not None and timeline.clock_sync.proof_state == "high_rtt"
        ),
        timing_unreliable_sensor_count=sum(
            1
            for timeline in timelines.values()
            if timeline.clock_sync is not None
            and timeline.clock_sync.proof_state == "timing_unreliable"
        ),
    )


def _summarize_raw_capture_losses(raw_capture: RawRunCapture) -> _RawCaptureLossCounts:
    return _RawCaptureLossCounts(
        dropped_chunk_count=raw_capture.manifest.total_dropped_chunk_count,
        late_packet_chunk_count=raw_capture.manifest.total_late_packet_chunk_count,
        queue_overflow_chunk_count=raw_capture.manifest.losses.queue_overflow_chunk_count,
        invalid_chunk_count=raw_capture.manifest.losses.invalid_chunk_count,
        write_error_chunk_count=raw_capture.manifest.losses.write_error_chunk_count,
        udp_ingest_queue_drop_count=raw_capture.manifest.losses.udp_ingest_queue_drop_count,
    )


def _build_fft_unavailable_replay_result(
    *,
    samples: tuple[SensorFrame, ...],
    raw_capture: RawRunCapture,
) -> RawReplayResult:
    loss_policy = assess_raw_capture_loss_policy(raw_capture.manifest)
    dropped_chunk_count = raw_capture.manifest.total_dropped_chunk_count
    late_packet_chunk_count = raw_capture.manifest.total_late_packet_chunk_count
    udp_ingest_queue_drop_count = raw_capture.manifest.losses.udp_ingest_queue_drop_count
    queue_overflow_chunk_count = raw_capture.manifest.losses.queue_overflow_chunk_count
    invalid_chunk_count = raw_capture.manifest.losses.invalid_chunk_count
    write_error_chunk_count = raw_capture.manifest.losses.write_error_chunk_count
    return RawReplayResult(
        samples=samples,
        summary=RawReplaySummary(
            raw_capture_available=True,
            raw_backed_summary_row_count=0,
            replay_window_count=len(samples),
            complete_window_count=0,
            partial_window_count=0,
            missing_window_count=len(samples),
            gap_count=0,
            overlap_count=0,
            dropped_chunk_count=dropped_chunk_count,
            late_packet_chunk_count=late_packet_chunk_count,
            queue_overflow_chunk_count=queue_overflow_chunk_count,
            invalid_chunk_count=invalid_chunk_count,
            write_error_chunk_count=write_error_chunk_count,
            timing_fallback_count=0,
            sample_rate_mismatch_count=0,
            fft_unusable_window_count=0,
            sample_rate_unverified_sensor_count=0,
            unanchored_sensor_count=0,
            legacy_sensor_count=0,
            sync_unverified_sensor_count=0,
            stale_sync_sensor_count=0,
            high_rtt_sensor_count=0,
            timing_unreliable_sensor_count=0,
            replay_confidence="fallback",
            raw_capture_mode="summary_only",
            raw_capture_loss_policy_severity=loss_policy.severity,
            raw_capture_loss_policy_reason=loss_policy.reason,
            raw_capture_loss_policy_max_sensor_drop_ratio=loss_policy.max_sensor_drop_ratio,
            raw_capture_loss_policy_max_events_per_minute=(
                loss_policy.max_sensor_loss_events_per_minute
            ),
            udp_ingest_queue_drop_count=udp_ingest_queue_drop_count,
            warnings=_build_replay_warnings(
                raw_backed_summary_row_count=0,
                timing_fallback_count=0,
                partial_window_count=0,
                missing_window_count=len(samples),
                gap_count=0,
                overlap_count=0,
                dropped_chunk_count=dropped_chunk_count,
                late_packet_chunk_count=late_packet_chunk_count,
                udp_ingest_queue_drop_count=udp_ingest_queue_drop_count,
                queue_overflow_chunk_count=queue_overflow_chunk_count,
                invalid_chunk_count=invalid_chunk_count,
                write_error_chunk_count=write_error_chunk_count,
                sample_rate_mismatch_count=0,
                fft_unusable_window_count=0,
                sample_rate_unverified_sensor_count=0,
                legacy_sensor_count=0,
                unanchored_sensor_count=0,
                sync_unverified_sensor_count=0,
                stale_sync_sensor_count=0,
                high_rtt_sensor_count=0,
                timing_unreliable_sensor_count=0,
                loss_policy=loss_policy,
            ),
        ),
        window_coverages=tuple(
            RawReplayWindowCoverage(
                client_id=sample.client_id,
                t_s=sample.t_s,
                coverage_state="missing",
                raw_backed=False,
                reason="fft_window_missing",
            )
            for sample in samples
        ),
    )


def _resolve_window(
    *,
    timeline: RawSensorTimeline,
    sample: SensorFrame,
    fft_n: int,
) -> _ResolvedWindow:
    requested_end_us, timing_source = _requested_end_us(timeline=timeline, sample=sample)
    if requested_end_us is None:
        return _ResolvedWindow(coverage_state="missing", reason="sample_time_missing")
    resolved = resolve_raw_window_end_time(
        timeline=timeline,
        requested_end_us=requested_end_us,
        sample_count=fft_n,
        timing_source=timing_source,
    )
    return _ResolvedWindow(
        coverage_state=resolved.coverage_state,
        reason=resolved.reason,
        segments=resolved.segments,
        timing_source=resolved.timing_source,
    )


def _requested_end_us(
    *,
    timeline: RawSensorTimeline,
    sample: SensorFrame,
) -> tuple[float | None, str]:
    run_start_monotonic_us = float(timeline.run_start_monotonic_us or 0)
    analysis_window_end_us = sample.analysis_window_end_us
    if analysis_window_end_us is not None:
        return run_start_monotonic_us + float(analysis_window_end_us), "explicit_window"
    if sample.t_s is None or not isfinite(sample.t_s) or sample.t_s <= 0:
        return None, "legacy_t_s"
    return run_start_monotonic_us + (float(sample.t_s) * 1_000_000.0), "legacy_t_s"


def _replay_confidence(
    *,
    raw_backed_summary_row_count: int,
    replay_window_count: int,
    partial_window_count: int,
    missing_window_count: int,
    gap_count: int,
    overlap_count: int,
    dropped_chunk_count: int,
    late_packet_chunk_count: int,
    sample_rate_mismatch_count: int,
    fft_unusable_window_count: int,
    sample_rate_unverified_sensor_count: int,
    sync_unverified_sensor_count: int,
    unanchored_sensor_count: int,
) -> RawReplayConfidence:
    if replay_window_count <= 0:
        return "unavailable"
    if raw_backed_summary_row_count <= 0:
        return "fallback"
    if (
        raw_backed_summary_row_count == replay_window_count
        and partial_window_count <= 0
        and missing_window_count <= 0
        and gap_count <= 0
        and overlap_count <= 0
        and dropped_chunk_count <= 0
        and late_packet_chunk_count <= 0
        and sample_rate_mismatch_count <= 0
        and fft_unusable_window_count <= 0
        and sample_rate_unverified_sensor_count <= 0
        and sync_unverified_sensor_count <= 0
        and unanchored_sensor_count <= 0
    ):
        return "full"
    return "partial"


def _build_replay_warnings(
    *,
    raw_backed_summary_row_count: int,
    timing_fallback_count: int,
    partial_window_count: int,
    missing_window_count: int,
    gap_count: int,
    overlap_count: int,
    dropped_chunk_count: int,
    late_packet_chunk_count: int,
    udp_ingest_queue_drop_count: int,
    queue_overflow_chunk_count: int,
    invalid_chunk_count: int,
    write_error_chunk_count: int,
    sample_rate_mismatch_count: int,
    fft_unusable_window_count: int,
    sample_rate_unverified_sensor_count: int,
    legacy_sensor_count: int,
    unanchored_sensor_count: int,
    sync_unverified_sensor_count: int,
    stale_sync_sensor_count: int,
    high_rtt_sensor_count: int,
    timing_unreliable_sensor_count: int,
    loss_policy: RawCaptureLossPolicyAssessment | None = None,
) -> tuple[RunContextWarning, ...]:
    if legacy_sensor_count > 0 and raw_backed_summary_row_count <= 0:
        return (
            RunContextWarning(
                code=WARNING_CODE_RAW_REPLAY_LEGACY_FALLBACK,
                severity="warn",
                applies_to="raw_replay",
                title=i18n_ref("RUN_CONTEXT_WARNING_RAW_REPLAY_LEGACY_TITLE"),
                detail=i18n_ref("RUN_CONTEXT_WARNING_RAW_REPLAY_LEGACY_DETAIL"),
            ),
        )
    warnings: list[RunContextWarning] = []
    if legacy_sensor_count > 0:
        warnings.append(
            RunContextWarning(
                code=WARNING_CODE_RAW_REPLAY_LEGACY_FALLBACK,
                severity="warn",
                applies_to="raw_replay",
                title=i18n_ref("RUN_CONTEXT_WARNING_RAW_REPLAY_LEGACY_TITLE"),
                detail=i18n_ref("RUN_CONTEXT_WARNING_RAW_REPLAY_LEGACY_DETAIL"),
            )
        )
    if sync_unverified_sensor_count > 0:
        missing_sync_sensor_count = max(
            0,
            sync_unverified_sensor_count
            - max(0, stale_sync_sensor_count)
            - max(0, high_rtt_sensor_count)
            - max(0, timing_unreliable_sensor_count),
        )
        warnings.append(
            RunContextWarning(
                code=WARNING_CODE_RAW_REPLAY_SYNC_UNVERIFIED,
                severity="warn",
                applies_to="raw_replay",
                title=i18n_ref("RUN_CONTEXT_WARNING_RAW_REPLAY_SYNC_UNVERIFIED_TITLE"),
                detail=i18n_ref(
                    "RUN_CONTEXT_WARNING_RAW_REPLAY_SYNC_UNVERIFIED_DETAIL",
                    sensors=str(max(0, sync_unverified_sensor_count)),
                    missing_sync=str(missing_sync_sensor_count),
                    stale=str(max(0, stale_sync_sensor_count)),
                    high_rtt=str(max(0, high_rtt_sensor_count)),
                    timing=str(max(0, timing_unreliable_sensor_count)),
                ),
            )
        )
    if timing_fallback_count > 0:
        warnings.append(
            RunContextWarning(
                code=WARNING_CODE_RAW_REPLAY_TIMING_FALLBACK,
                severity="warn",
                applies_to="raw_replay",
                title=i18n_ref("RUN_CONTEXT_WARNING_RAW_REPLAY_TIMING_FALLBACK_TITLE"),
                detail=i18n_ref(
                    "RUN_CONTEXT_WARNING_RAW_REPLAY_TIMING_FALLBACK_DETAIL",
                    count=str(max(0, timing_fallback_count)),
                ),
            )
        )
    if fft_unusable_window_count > 0:
        warnings.append(
            RunContextWarning(
                code=WARNING_CODE_RAW_REPLAY_FFT_UNUSABLE,
                severity="warn",
                applies_to="raw_replay",
                title=i18n_ref("RUN_CONTEXT_WARNING_RAW_REPLAY_FFT_UNUSABLE_TITLE"),
                detail=i18n_ref(
                    "RUN_CONTEXT_WARNING_RAW_REPLAY_FFT_UNUSABLE_DETAIL",
                    count=str(max(0, fft_unusable_window_count)),
                ),
            )
        )
    if dropped_chunk_count > 0 or late_packet_chunk_count > 0:
        warnings.append(
            RunContextWarning(
                code=WARNING_CODE_RAW_REPLAY_DROPPED_CHUNKS,
                severity="warn",
                applies_to="raw_replay",
                title=i18n_ref("RUN_CONTEXT_WARNING_RAW_REPLAY_DROPPED_CHUNKS_TITLE"),
                detail=i18n_ref(
                    "RUN_CONTEXT_WARNING_RAW_REPLAY_DROPPED_CHUNKS_DETAIL",
                    count=str(max(0, dropped_chunk_count + late_packet_chunk_count)),
                    late=str(max(0, late_packet_chunk_count)),
                    udp_ingest=str(max(0, udp_ingest_queue_drop_count)),
                    queue_overflow=str(max(0, queue_overflow_chunk_count)),
                    invalid=str(max(0, invalid_chunk_count)),
                    write_errors=str(max(0, write_error_chunk_count)),
                ),
            )
        )
    if loss_policy is not None and loss_policy.severity in {"degraded", "fatal"}:
        max_drop_percent = max(0.0, loss_policy.max_sensor_drop_ratio) * 100.0
        max_events_per_minute = max(0.0, loss_policy.max_sensor_loss_events_per_minute)
        warnings.append(
            RunContextWarning(
                code=WARNING_CODE_RAW_CAPTURE_LOSS_POLICY,
                severity="error" if loss_policy.severity == "fatal" else "warn",
                applies_to="raw_capture",
                title=i18n_ref("RUN_CONTEXT_WARNING_RAW_CAPTURE_LOSS_POLICY_TITLE"),
                detail=i18n_ref(
                    "RUN_CONTEXT_WARNING_RAW_CAPTURE_LOSS_POLICY_DETAIL",
                    severity=loss_policy.severity,
                    reason=loss_policy.reason,
                    sensors=str(max(0, int(loss_policy.affected_sensor_count))),
                    queue_overflow=str(max(0, queue_overflow_chunk_count)),
                    dropped=str(max(0, dropped_chunk_count)),
                    max_drop_percent=f"{max_drop_percent:.2f}",
                    max_events_per_minute=f"{max_events_per_minute:.2f}",
                ),
            )
        )
    if (
        partial_window_count <= 0
        and missing_window_count <= 0
        and gap_count <= 0
        and overlap_count <= 0
        and sample_rate_mismatch_count <= 0
        and sample_rate_unverified_sensor_count <= 0
    ):
        return tuple(warnings)
    warnings.append(
        RunContextWarning(
            code=WARNING_CODE_RAW_REPLAY_COVERAGE_INCOMPLETE,
            severity="warn",
            applies_to="raw_replay",
            title=i18n_ref("RUN_CONTEXT_WARNING_RAW_REPLAY_INCOMPLETE_TITLE"),
            detail=i18n_ref(
                "RUN_CONTEXT_WARNING_RAW_REPLAY_INCOMPLETE_DETAIL",
                partial=str(max(0, partial_window_count)),
                missing=str(max(0, missing_window_count)),
                gaps=str(max(0, gap_count)),
                overlaps=str(max(0, overlap_count)),
                mismatches=str(max(0, sample_rate_mismatch_count)),
                unverified_rates=str(max(0, sample_rate_unverified_sensor_count)),
            ),
        )
    )
    return tuple(warnings)
