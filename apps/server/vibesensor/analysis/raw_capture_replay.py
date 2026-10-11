"""Raw-capture replay helpers for post-stop analysis."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from math import nan
from typing import Literal, cast

import numpy as np
import numpy.typing as npt
from numpy.lib.stride_tricks import as_strided

from vibesensor.common.json_utils import i18n_ref
from vibesensor.dsp.constants import SPECTRUM_MAX_HZ, SPECTRUM_MIN_HZ
from vibesensor.dsp.fft_analysis import SpectralAnalysisComputer
from vibesensor.dsp.vibration_strength import StrengthRows
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
from vibesensor.recording.sample_columns import SampleColumns, optional_floats, rows_of_groups
from vibesensor.recording.sample_peaks import SamplePeaks
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
    "replay_raw_windows",
]

type RawReplayCoverageState = Literal["complete", "partial", "missing"]
type RawReplayConfidence = Literal["full", "partial", "fallback", "unavailable"]
type RawCaptureMode = Literal["raw_backed", "partial_raw_backed", "summary_only"]

# Raw windows whose strengths are taken together: enough to share the per-call
# cost of the strength pipeline, few enough to hold little memory.
_WINDOWS_PER_BATCH = 128
# Raw windows whose spectra an FFT thread computes at once
# (``combined_spectra``). On the Pi 3 A+ larger chunks gain nothing and hold
# more memory (docs/multithreading_performance.md).
_WINDOWS_PER_FFT = 64
# The most a chunk's windows may span, as the bytes of the strided view of
# every window there, to be gathered in one step: well within what numpy
# allows a view on a 32-bit system (the Pi's).
_MAX_GATHER_VIEW_BYTES = 1 << 30
# Threads computing the spectra, and chunks queued for them: enough to keep
# them busy. Since the strengths are taken as columns, one FFT thread is what
# the replay waits on; a second one takes 1.7 s off a 30-minute drive's
# replay on the Pi 3 A+ for ~6 MB (docs/multithreading_performance.md).
_FFT_WORKERS = 2
_FFT_CHUNKS_AHEAD = 3


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
    """The replay's coverage facts, and the peaks of the samples it rebuilt.

    The replay rebuilds a sample's strength fields in place; ``rebuilt`` says
    which samples it rebuilt, and ``peaks`` holds their peaks (none for the
    others, whose stored peaks stand).
    """

    summary: RawReplaySummary
    peaks: SamplePeaks
    rebuilt: npt.NDArray[np.bool_]
    window_coverages: tuple[RawReplayWindowCoverage, ...] = ()


@dataclass(frozen=True, slots=True)
class _ResolvedWindow:
    coverage_state: RawReplayCoverageState
    reason: str | None
    segments: tuple[RawWindowSegment, ...] = ()
    timing_source: str = "explicit_window"


@dataclass(frozen=True, slots=True)
class _SensorRequests:
    """One sensor's samples whose raw window is looked for, and when each window ends."""

    client_id: str
    timeline: RawSensorTimeline
    sensor_data: RawCaptureSensorData
    sample_rate_hz: int
    rows: npt.NDArray[np.intp]
    # On the sensor's clock (``_requested_end_us``); NaN without a sample time.
    requested_end_us: npt.NDArray[np.float64]
    # Those whose window end is the sample time's (``legacy_t_s``).
    by_sample_time: list[bool]
    # The coverage reason each window has when complete.
    reasons: list[str | None]


@dataclass(frozen=True, slots=True)
class _RawWindow:
    """A complete raw window (of sample *row*), its spectrum still to be computed.

    Where its samples start in the sensor's raw buffer, or (-1) the ``(N, 3)``
    counts assembled from its segments where they do not follow on there.
    """

    row: int
    reason: str | None
    raw_start: int
    samples_i16: npt.NDArray[np.int16] | None = None


@dataclass(frozen=True, slots=True)
class _WindowSpectra:
    """Each window's spectrum as a row (``None``: no analysis bins), its last and mean reading."""

    spectra: npt.NDArray[np.float32] | None
    # ``(N, 3)``.
    last_xyz: npt.NDArray[np.float32]
    mean_xyz: list[tuple[float, float, float]]


@dataclass(frozen=True, slots=True)
class _ReplayBuildContext:
    fft_n: int
    timelines: dict[str, RawSensorTimeline]
    fft_computer: SpectralAnalysisComputer
    accel_scale_g_per_lsb: float | None


@dataclass(frozen=True, slots=True)
class _ReplayWindowBuildResult:
    coverages: tuple[RawReplayWindowCoverage, ...]
    peaks: _RebuiltPeaks
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


class _RebuiltPeaks:
    """The samples the replay rebuilds, and their peaks, gathered as it rebuilds them."""

    __slots__ = ("amp", "hz", "local_floor_amp_g", "rebuilt", "rows")

    def __init__(self, size: int) -> None:
        self.rebuilt = np.zeros(size, dtype=np.bool_)
        self.rows: list[npt.NDArray[np.intp]] = []
        self.hz: list[npt.NDArray[np.float64]] = []
        self.amp: list[npt.NDArray[np.float64]] = []
        self.local_floor_amp_g: list[npt.NDArray[np.float64]] = []

    def add(self, indexes: npt.NDArray[np.intp], strengths: StrengthRows) -> None:
        """Samples *indexes* rebuilt, with the peaks of *strengths*' rows in turn.

        Those of finite frequency and amplitude over 0; NaN for a local floor
        that is not finite.
        """
        self.rebuilt[indexes] = True
        hz, amp = strengths.peak_hz, strengths.peak_amp
        kept = np.isfinite(hz) & np.isfinite(amp) & (hz > 0) & (amp > 0)
        local_floor = strengths.peak_local_floor_amp_g[kept]
        self.rows.append(indexes[strengths.peak_row[kept]])
        self.hz.append(hz[kept])
        self.amp.append(amp[kept])
        self.local_floor_amp_g.append(np.where(np.isfinite(local_floor), local_floor, nan))

    def peaks(self) -> SamplePeaks:
        size = int(self.rebuilt.size)
        if not self.rows:
            return SamplePeaks.none(size)
        return SamplePeaks.of_peaks(
            np.concatenate(self.rows),
            np.concatenate(self.hz),
            np.concatenate(self.amp),
            np.concatenate(self.local_floor_amp_g),
            size,
        )


def replay_raw_windows(
    *,
    samples: SampleColumns,
    metadata: RunMetadata,
    raw_capture: RawRunCapture | None,
) -> RawReplayResult:
    """Rebuild each sample's strength from its raw window, where it has a complete one.

    A rebuilt sample's strength fields (its last reading per axis, strength,
    bucket, peak and floor amplitude, and spectrum) are set in place; its
    peaks are the result's. A sample without a complete raw window keeps its
    stored ones.
    """

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
        peaks=windows.peaks.peaks(),
        rebuilt=windows.peaks.rebuilt,
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


def _sensor_requests(
    *,
    samples: SampleColumns,
    raw_capture: RawRunCapture,
    timelines: dict[str, RawSensorTimeline],
    coverages: list[RawReplayWindowCoverage | None],
    times: list[float | None],
) -> list[_SensorRequests]:
    """Each sensor's samples whose raw window is looked for, in the order their first comes.

    The others get their coverage, and why they have no raw window, in *coverages*.
    """
    client_of, client_ids = samples.clients()
    found: list[_SensorRequests] = []
    for client_id, rows in zip(client_ids, rows_of_groups(client_of, len(client_ids)), strict=True):
        timeline = timelines.get(client_id)
        sensor_data = raw_capture.sensor_data(client_id)
        if timeline is None or sensor_data is None:
            _uncover(coverages, rows, client_id, times, "sensor_missing")
            continue
        sensor_manifest = sensor_data.manifest
        sample_rate_hz = int(sensor_manifest.sample_rate_hz or timeline.sample_rate_hz or 0)
        if sample_rate_hz <= 0:
            _uncover(coverages, rows, client_id, times, "sample_rate_missing")
            continue
        requested_rates = samples.sample_rate_hz[rows]
        mismatch = (requested_rates > 0) & (requested_rates != sample_rate_hz)
        if sensor_manifest.sample_rate_unverified:
            _uncover(coverages, rows[mismatch], client_id, times, "sample_rate_mismatch")
            rows, mismatch = rows[~mismatch], mismatch[~mismatch]
            if not rows.size:
                continue
        requested_end_us, by_sample_time = _requested_end_us(
            timeline=timeline, samples=samples, rows=rows
        )
        found.append(
            _SensorRequests(
                client_id=client_id,
                timeline=timeline,
                sensor_data=sensor_data,
                sample_rate_hz=sample_rate_hz,
                rows=rows,
                requested_end_us=requested_end_us,
                by_sample_time=by_sample_time.tolist(),
                reasons=[
                    "sample_rate_mismatch"
                    if mismatched
                    else ("timing_fallback" if legacy else None)
                    for mismatched, legacy in zip(
                        mismatch.tolist(), by_sample_time.tolist(), strict=True
                    )
                ],
            )
        )
    found.sort(key=lambda sensor: int(sensor.rows[0]))
    return found


def _uncover(
    coverages: list[RawReplayWindowCoverage | None],
    rows: npt.NDArray[np.intp],
    client_id: str,
    times: list[float | None],
    reason: str,
) -> None:
    """The coverage of samples *rows* (of sensor *client_id*), which have no raw window."""
    for row in rows.tolist():
        coverages[row] = _uncovered(client_id, times[row], "missing", reason)


def _uncovered(
    client_id: str, t_s: float | None, coverage_state: RawReplayCoverageState, reason: str | None
) -> RawReplayWindowCoverage:
    """A sample's coverage without a complete raw window, and why: it is not rebuilt."""
    return RawReplayWindowCoverage(
        client_id=client_id,
        t_s=t_s,
        coverage_state=coverage_state,
        raw_backed=False,
        reason=reason,
    )


def _segmented_window(
    *,
    sensor: _SensorRequests,
    position: int,
    t_s: float | None,
    fft_n: int,
) -> RawReplayWindowCoverage | _RawWindow:
    """Sensor request *position*'s window, resolved on its own: incomplete, or in pieces."""
    requested_end_us = float(sensor.requested_end_us[position])
    window = _resolve_window(
        timeline=sensor.timeline,
        requested_end_us=None if np.isnan(requested_end_us) else requested_end_us,
        timing_source="legacy_t_s" if sensor.by_sample_time[position] else "explicit_window",
        fft_n=fft_n,
    )
    if window.coverage_state != "complete" or not window.segments:
        coverage_reason = (
            "timing_fallback" if window.timing_source == "legacy_t_s" else window.reason
        )
        return _uncovered(sensor.client_id, t_s, window.coverage_state, coverage_reason)
    window_i16 = assemble_raw_window_samples(
        sensor_data=sensor.sensor_data, segments=window.segments
    )
    if window_i16.shape[0] != fft_n:
        return _uncovered(sensor.client_id, t_s, "partial", "window_truncated")
    return _RawWindow(
        row=int(sensor.rows[position]),
        reason=sensor.reasons[position],
        raw_start=-1,
        samples_i16=window_i16,
    )


def _window_spectra(
    windows: Sequence[_RawWindow],
    sensor_data: RawCaptureSensorData,
    sample_rate_hz: int,
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
    # A copy: the FFT overwrites the blocks.
    last_xyz = blocks[:, :, -1].copy()
    means = np.mean(padded, axis=2, keepdims=True)
    mean_xyz = [tuple(mean) for mean in means[: len(windows), :, 0].tolist()]
    spectra = fft_computer.combined_spectra(padded, sample_rate_hz, means=means)
    if spectra is not None:
        spectra = spectra[: len(windows)]
    return _WindowSpectra(
        spectra=spectra,
        last_xyz=last_xyz,
        mean_xyz=cast("list[tuple[float, float, float]]", mean_xyz),
    )


def _set_last_readings(
    samples: SampleColumns, rows: npt.NDArray[np.intp], last_xyz: npt.NDArray[np.float32]
) -> None:
    """Set samples *rows*' last reading per axis to *last_xyz*' rows in turn."""
    samples.accel_x_g[rows] = last_xyz[:, 0]
    samples.accel_y_g[rows] = last_xyz[:, 1]
    samples.accel_z_g[rows] = last_xyz[:, 2]


def _set_no_strengths(samples: SampleColumns, rows: npt.NDArray[np.intp]) -> None:
    """Rebuild samples *rows* without strength, where the spectrum has no analysis bins."""
    samples.vibration_strength_db[rows] = nan
    samples.strength_bucket_of[rows] = -1
    samples.strength_peak_amp_g[rows] = nan
    samples.strength_floor_amp_g[rows] = nan


def _set_strengths(
    samples: SampleColumns, rows: npt.NDArray[np.intp], strengths: StrengthRows
) -> None:
    """Set samples *rows*' strength fields from *strengths*' rows in turn.

    As ``strength_metrics_from_mapping`` takes them from the metrics: a value
    that is not finite is none (NaN).
    """
    for column, values in (
        (samples.vibration_strength_db, strengths.first_peak(strengths.peak_db)),
        (samples.strength_peak_amp_g, strengths.first_peak(strengths.peak_amp)),
        (samples.strength_floor_amp_g, strengths.noise_floor_amp_g),
    ):
        column[rows] = np.where(np.isfinite(values), values, nan)
    samples.set_strength_buckets(rows.tolist(), strengths.strength_buckets())


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


def _missing_coverages(samples: SampleColumns, reason: str) -> tuple[RawReplayWindowCoverage, ...]:
    """Each sample's coverage where none has a raw window, for *reason*."""
    client_of, client_ids = samples.clients()
    return tuple(
        _uncovered(client_ids[client], t_s, "missing", reason)
        for client, t_s in zip(client_of.tolist(), optional_floats(samples.t_s), strict=True)
    )


def _build_raw_capture_unavailable_replay_result(
    samples: SampleColumns,
) -> RawReplayResult:
    return RawReplayResult(
        peaks=SamplePeaks.none(len(samples)),
        rebuilt=np.zeros(len(samples), dtype=np.bool_),
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
        window_coverages=_missing_coverages(samples, "raw_capture_unavailable"),
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
    samples: SampleColumns,
    raw_capture: RawRunCapture,
    context: _ReplayBuildContext,
) -> _ReplayWindowBuildResult:
    coverages, rebuilt = _rebuild_samples(samples=samples, raw_capture=raw_capture, context=context)
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
        coverages=tuple(coverages),
        peaks=rebuilt,
        raw_backed_count=raw_backed_count,
        complete_window_count=complete_window_count,
        partial_window_count=partial_window_count,
        missing_window_count=missing_window_count,
        sample_rate_mismatch_count=sample_rate_mismatch_count,
        timing_fallback_count=timing_fallback_count,
        fft_unusable_window_count=fft_unusable_window_count,
    )


def _rebuild_samples(
    *,
    samples: SampleColumns,
    raw_capture: RawRunCapture,
    context: _ReplayBuildContext,
) -> tuple[list[RawReplayWindowCoverage], _RebuiltPeaks]:
    """Rebuild each sample from its raw window: each one's window coverage, in order, and the peaks.

    Sensor by sensor, the windows are found in the raw capture all at once
    (``contiguous_raw_window_starts``; one at a time only where a window is
    incomplete or in pieces). Their spectra are computed ``_WINDOWS_PER_FFT``
    at a time on ``_FFT_WORKERS`` threads (``combined_spectra``, most of whose
    work runs with the GIL released), while this thread takes the finished spectra's
    strengths ``_WINDOWS_PER_BATCH`` at a time. Each result is the one the
    window has on its own.
    """
    rebuilt = _RebuiltPeaks(len(samples))
    coverages: list[RawReplayWindowCoverage | None] = [None] * len(samples)
    times = optional_floats(samples.t_s)
    # Each sample rate's spectra, kept together as the rows of one array
    # (``WindowSpectrum.rows``), and how many rows are filled. Rows are taken
    # in turn, so only those filled take up memory.
    kept: dict[int, tuple[npt.NDArray[np.float32], list[int]]] = {}
    # Each sample rate's samples whose strength is still to be taken: those of
    # its last filled rows, in order.
    pending: dict[int, list[int]] = defaultdict(list)
    in_flight: deque[tuple[_SensorRequests, list[_RawWindow], Future[_WindowSpectra]]] = deque()

    def finish(sample_rate_hz: int) -> None:
        """Take the strengths of the first ``_WINDOWS_PER_BATCH`` (at most) pending samples."""
        waiting = pending[sample_rate_hz]
        rows, filled = kept[sample_rate_hz]
        first = filled[0] - len(waiting)
        count = min(len(waiting), _WINDOWS_PER_BATCH)
        indexes = np.array(waiting[:count], dtype=np.intp)
        del waiting[:count]
        strengths = context.fft_computer.combined_strengths(
            rows[first : first + count], sample_rate_hz
        )
        rebuilt.add(indexes, strengths)
        _set_strengths(samples, indexes, strengths)

    def take_oldest() -> None:
        sensor, chunk, future = in_flight.popleft()
        computed = future.result()
        indexes = np.array([window.row for window in chunk], dtype=np.intp)
        _set_last_readings(samples, indexes, computed.last_xyz)
        if computed.spectra is None:
            # The sample rate leaves the spectrum no analysis bins: no strength, no peaks.
            _set_no_strengths(samples, indexes)
            rebuilt.rebuilt[indexes] = True
            for window, mean_xyz in zip(chunk, computed.mean_xyz, strict=True):
                coverages[window.row] = RawReplayWindowCoverage(
                    client_id=sensor.client_id,
                    t_s=times[window.row],
                    coverage_state="complete",
                    raw_backed=False,
                    reason="fft_no_valid_bins",
                    mean_xyz=mean_xyz,
                )
            return
        sample_rate_hz = sensor.sample_rate_hz
        freq_hz = context.fft_computer.freq_slice(sample_rate_hz)
        if sample_rate_hz not in kept:
            kept[sample_rate_hz] = (np.empty((len(samples), freq_hz.size), dtype=np.float32), [0])
        rows, filled = kept[sample_rate_hz]
        first = filled[0]
        rows[first : first + len(chunk)] = computed.spectra
        filled[0] += len(chunk)
        waiting = pending[sample_rate_hz]
        # Each sample's strength follows, with its batch's (``finish``).
        for position, (window, mean_xyz) in enumerate(zip(chunk, computed.mean_xyz, strict=True)):
            samples.spectra[window.row] = WindowSpectrum(
                freq_hz=freq_hz, amp_g=rows[first + position], rows=rows, row=first + position
            )
            coverages[window.row] = RawReplayWindowCoverage(
                client_id=sensor.client_id,
                t_s=times[window.row],
                coverage_state="complete",
                raw_backed=True,
                reason=window.reason,
                mean_xyz=mean_xyz,
            )
        waiting.extend(indexes.tolist())
        while len(waiting) >= _WINDOWS_PER_BATCH:
            finish(sample_rate_hz)

    sensors = _sensor_requests(
        samples=samples,
        raw_capture=raw_capture,
        timelines=context.timelines,
        coverages=coverages,
        times=times,
    )
    with ThreadPoolExecutor(max_workers=_FFT_WORKERS, thread_name_prefix="raw-replay-fft") as pool:

        def submit(sensor: _SensorRequests, chunk: list[_RawWindow]) -> None:
            in_flight.append(
                (
                    sensor,
                    chunk,
                    pool.submit(
                        _window_spectra,
                        chunk,
                        sensor.sensor_data,
                        sensor.sample_rate_hz,
                        context.fft_computer,
                        context.fft_n,
                        context.accel_scale_g_per_lsb,
                    ),
                )
            )
            while len(in_flight) > _FFT_CHUNKS_AHEAD:
                take_oldest()

        for sensor in sensors:
            raw_starts = contiguous_raw_window_starts(
                timeline=sensor.timeline,
                requested_end_us=sensor.requested_end_us,
                sample_count=context.fft_n,
            )
            chunk: list[_RawWindow] = []
            for position, (row, reason, raw_start) in enumerate(
                zip(sensor.rows.tolist(), sensor.reasons, raw_starts.tolist(), strict=True)
            ):
                window = (
                    _RawWindow(row=row, reason=reason, raw_start=raw_start)
                    if raw_start >= 0
                    else _segmented_window(
                        sensor=sensor, position=position, t_s=times[row], fft_n=context.fft_n
                    )
                )
                if not isinstance(window, _RawWindow):
                    coverages[row] = window
                    continue
                chunk.append(window)
                if len(chunk) >= _WINDOWS_PER_FFT:
                    submit(sensor, chunk)
                    chunk = []
            if chunk:
                submit(sensor, chunk)
        while in_flight:
            take_oldest()
    for sample_rate_hz, waiting in pending.items():
        if waiting:
            finish(sample_rate_hz)
    # Every sample has its coverage by now.
    return cast("list[RawReplayWindowCoverage]", coverages), rebuilt


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
    samples: SampleColumns,
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
        peaks=SamplePeaks.none(len(samples)),
        rebuilt=np.zeros(len(samples), dtype=np.bool_),
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
        window_coverages=_missing_coverages(samples, "fft_window_missing"),
    )


def _resolve_window(
    *,
    timeline: RawSensorTimeline,
    requested_end_us: float | None,
    timing_source: str,
    fft_n: int,
) -> _ResolvedWindow:
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
    samples: SampleColumns,
    rows: npt.NDArray[np.intp],
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.bool_]]:
    """When samples *rows*' raw windows end on the sensor's clock (NaN: no sample time).

    And which of them go by the sample time (``legacy_t_s``): those without
    an analysis window end.
    """
    run_start_monotonic_us = float(timeline.run_start_monotonic_us or 0)
    analysis_window_end_us = samples.analysis_window_end_us[rows]
    t_s = samples.t_s[rows]
    by_sample_time = np.isnan(analysis_window_end_us)
    timed = np.isfinite(t_s) & (t_s > 0)
    requested_end_us = np.where(
        by_sample_time,
        np.where(timed, run_start_monotonic_us + (t_s * 1_000_000.0), nan),
        run_start_monotonic_us + analysis_window_end_us,
    )
    return requested_end_us, by_sample_time


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
