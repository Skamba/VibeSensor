"""Raw-capture replay helpers for post-stop analysis."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from typing import Literal

import numpy as np

from vibesensor.domain.strength_metrics import StrengthMetrics
from vibesensor.shared.boundaries.codecs import strength_metrics_from_mapping
from vibesensor.shared.constants.dsp import SPECTRUM_MAX_HZ, SPECTRUM_MIN_HZ
from vibesensor.shared.fft_analysis import SpectralAnalysisComputer, medfilt3
from vibesensor.shared.json_utils import i18n_ref
from vibesensor.shared.run_context_warning import (
    WARNING_CODE_RAW_REPLAY_COVERAGE_INCOMPLETE,
    WARNING_CODE_RAW_REPLAY_DROPPED_CHUNKS,
    WARNING_CODE_RAW_REPLAY_LEGACY_FALLBACK,
    WARNING_CODE_RAW_REPLAY_TIMING_FALLBACK,
    RunContextWarning,
)
from vibesensor.shared.types.raw_capture import RawCaptureSensorData, RawRunCapture
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame

__all__ = [
    "RawReplayResult",
    "RawReplaySummary",
    "RawReplayWindowCoverage",
    "build_raw_backed_samples",
]

type RawReplayCoverageState = Literal["complete", "partial", "missing"]
type RawReplayConfidence = Literal["full", "partial", "fallback", "unavailable"]
_TIMING_TOLERANCE_SAMPLES = 0.75


@dataclass(frozen=True, slots=True)
class RawReplayWindowCoverage:
    """Per-window replay coverage classification for one persisted summary sample."""

    client_id: str
    t_s: float | None
    coverage_state: RawReplayCoverageState
    raw_backed: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RawReplaySummary:
    """Rolled-up replay coverage facts persisted into analysis metadata."""

    raw_capture_available: bool
    raw_backed_sample_count: int
    replay_window_count: int
    complete_window_count: int
    partial_window_count: int
    missing_window_count: int
    gap_count: int
    overlap_count: int
    dropped_chunk_count: int
    queue_overflow_chunk_count: int
    invalid_chunk_count: int
    write_error_chunk_count: int
    timing_fallback_count: int
    sample_rate_mismatch_count: int
    unanchored_sensor_count: int
    replay_confidence: RawReplayConfidence
    raw_capture_mode: str
    warnings: tuple[RunContextWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class RawReplayResult:
    """Replay result carrying rebuilt samples plus structured coverage metadata."""

    samples: tuple[SensorFrame, ...]
    summary: RawReplaySummary
    window_coverages: tuple[RawReplayWindowCoverage, ...] = ()


@dataclass(frozen=True, slots=True)
class _TimelineInterval:
    start_us: float
    end_us: float


@dataclass(frozen=True, slots=True)
class _TimelineChunk:
    """Chronological chunk timing plus append-order raw-buffer offsets."""

    sample_start: int
    sample_end: int
    start_us: float
    end_us: float


@dataclass(frozen=True, slots=True)
class _SensorTimeline:
    client_id: str
    sample_rate_hz: int
    sample_period_us: float
    chunks: tuple[_TimelineChunk, ...]
    gap_intervals: tuple[_TimelineInterval, ...]
    overlap_intervals: tuple[_TimelineInterval, ...]
    run_start_monotonic_us: int | None
    anchored: bool

    @property
    def timing_tolerance_us(self) -> float:
        return max(1.0, self.sample_period_us * _TIMING_TOLERANCE_SAMPLES)


@dataclass(frozen=True, slots=True)
class _ResolvedWindow:
    coverage_state: RawReplayCoverageState
    reason: str | None
    segments: tuple[_WindowSegment, ...] = ()
    timing_source: str = "explicit_window"


@dataclass(frozen=True, slots=True)
class _WindowSegment:
    sample_start: int
    sample_end: int


def build_raw_backed_samples(
    *,
    samples: tuple[SensorFrame, ...],
    metadata: RunMetadata,
    raw_capture: RawRunCapture | None,
) -> RawReplayResult:
    """Replace summary strength metrics with raw-backed metrics when possible."""

    if raw_capture is None:
        return RawReplayResult(
            samples=samples,
            summary=RawReplaySummary(
                raw_capture_available=False,
                raw_backed_sample_count=0,
                replay_window_count=len(samples),
                complete_window_count=0,
                partial_window_count=0,
                missing_window_count=len(samples),
                gap_count=0,
                overlap_count=0,
                dropped_chunk_count=0,
                queue_overflow_chunk_count=0,
                invalid_chunk_count=0,
                write_error_chunk_count=0,
                timing_fallback_count=0,
                sample_rate_mismatch_count=0,
                unanchored_sensor_count=0,
                replay_confidence="unavailable",
                raw_capture_mode="summary_only",
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
    fft_n = int(metadata.fft_window_size_samples or 0)
    if fft_n <= 0:
        return RawReplayResult(
            samples=samples,
            summary=RawReplaySummary(
                raw_capture_available=True,
                raw_backed_sample_count=0,
                replay_window_count=len(samples),
                complete_window_count=0,
                partial_window_count=0,
                missing_window_count=len(samples),
                gap_count=0,
                overlap_count=0,
                dropped_chunk_count=0,
                queue_overflow_chunk_count=0,
                invalid_chunk_count=0,
                write_error_chunk_count=0,
                timing_fallback_count=0,
                sample_rate_mismatch_count=0,
                unanchored_sensor_count=0,
                replay_confidence="fallback",
                raw_capture_mode="summary_only",
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
    timelines = {
        sensor.manifest.client_id: _build_sensor_timeline(
            raw_capture, sensor_id=sensor.manifest.client_id
        )
        for sensor in raw_capture.sensors
    }
    fft_computer = _build_fft_computer(metadata)
    replayed: list[SensorFrame] = []
    coverages: list[RawReplayWindowCoverage] = []
    complete_window_count = 0
    partial_window_count = 0
    missing_window_count = 0
    sample_rate_mismatch_count = 0
    timing_fallback_count = 0
    raw_backed_count = 0
    scale = metadata.accel_scale_g_per_lsb
    for sample in samples:
        rebuilt, coverage = _rebuild_sample(
            sample=sample,
            timeline=timelines.get(sample.client_id),
            raw_capture=raw_capture,
            fft_computer=fft_computer,
            fft_n=fft_n,
            accel_scale_g_per_lsb=scale,
        )
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
        replayed.append(rebuilt)
        coverages.append(coverage)
    gap_count = sum(len(timeline.gap_intervals) for timeline in timelines.values())
    overlap_count = sum(len(timeline.overlap_intervals) for timeline in timelines.values())
    unanchored_sensor_count = sum(1 for timeline in timelines.values() if not timeline.anchored)
    dropped_chunk_count = raw_capture.manifest.total_dropped_chunk_count
    queue_overflow_chunk_count = raw_capture.manifest.losses.queue_overflow_chunk_count
    invalid_chunk_count = raw_capture.manifest.losses.invalid_chunk_count
    write_error_chunk_count = raw_capture.manifest.losses.write_error_chunk_count
    replay_confidence = _replay_confidence(
        raw_backed_sample_count=raw_backed_count,
        replay_window_count=len(samples),
        partial_window_count=partial_window_count,
        missing_window_count=missing_window_count,
        gap_count=gap_count,
        overlap_count=overlap_count,
        dropped_chunk_count=dropped_chunk_count,
        sample_rate_mismatch_count=sample_rate_mismatch_count,
        unanchored_sensor_count=unanchored_sensor_count,
    )
    raw_capture_mode = (
        "summary_only"
        if raw_backed_count <= 0
        else ("raw_backed" if replay_confidence == "full" else "partial_raw_backed")
    )
    return RawReplayResult(
        samples=tuple(replayed),
        summary=RawReplaySummary(
            raw_capture_available=True,
            raw_backed_sample_count=raw_backed_count,
            replay_window_count=len(samples),
            complete_window_count=complete_window_count,
            partial_window_count=partial_window_count,
            missing_window_count=missing_window_count,
            gap_count=gap_count,
            overlap_count=overlap_count,
            dropped_chunk_count=dropped_chunk_count,
            queue_overflow_chunk_count=queue_overflow_chunk_count,
            invalid_chunk_count=invalid_chunk_count,
            write_error_chunk_count=write_error_chunk_count,
            timing_fallback_count=timing_fallback_count,
            sample_rate_mismatch_count=sample_rate_mismatch_count,
            unanchored_sensor_count=unanchored_sensor_count,
            replay_confidence=replay_confidence,
            raw_capture_mode=raw_capture_mode,
            warnings=_build_replay_warnings(
                raw_backed_sample_count=raw_backed_count,
                timing_fallback_count=timing_fallback_count,
                partial_window_count=partial_window_count,
                missing_window_count=missing_window_count,
                gap_count=gap_count,
                overlap_count=overlap_count,
                dropped_chunk_count=dropped_chunk_count,
                queue_overflow_chunk_count=queue_overflow_chunk_count,
                invalid_chunk_count=invalid_chunk_count,
                write_error_chunk_count=write_error_chunk_count,
                sample_rate_mismatch_count=sample_rate_mismatch_count,
                unanchored_sensor_count=unanchored_sensor_count,
            ),
        ),
        window_coverages=tuple(coverages),
    )


def _rebuild_sample(
    *,
    sample: SensorFrame,
    timeline: _SensorTimeline | None,
    raw_capture: RawRunCapture,
    fft_computer: SpectralAnalysisComputer,
    fft_n: int,
    accel_scale_g_per_lsb: float | None,
) -> tuple[SensorFrame, RawReplayWindowCoverage]:
    if timeline is None:
        return (
            sample,
            RawReplayWindowCoverage(
                client_id=sample.client_id,
                t_s=sample.t_s,
                coverage_state="missing",
                raw_backed=False,
                reason="sensor_missing",
            ),
        )
    sensor_data = raw_capture.sensor_data(sample.client_id)
    if sensor_data is None:
        return (
            sample,
            RawReplayWindowCoverage(
                client_id=sample.client_id,
                t_s=sample.t_s,
                coverage_state="missing",
                raw_backed=False,
                reason="sensor_missing",
            ),
        )
    sample_rate_hz = int(sample.sample_rate_hz or timeline.sample_rate_hz or 0)
    if sample_rate_hz <= 0:
        return (
            sample,
            RawReplayWindowCoverage(
                client_id=sample.client_id,
                t_s=sample.t_s,
                coverage_state="missing",
                raw_backed=False,
                reason="sample_rate_missing",
            ),
        )
    if sample_rate_hz != timeline.sample_rate_hz:
        return (
            sample,
            RawReplayWindowCoverage(
                client_id=sample.client_id,
                t_s=sample.t_s,
                coverage_state="missing",
                raw_backed=False,
                reason="sample_rate_mismatch",
            ),
        )
    window = _resolve_window(timeline=timeline, sample=sample, fft_n=fft_n)
    if window.coverage_state != "complete" or not window.segments:
        coverage_reason = (
            "timing_fallback" if window.timing_source == "legacy_t_s" else window.reason
        )
        return (
            sample,
            RawReplayWindowCoverage(
                client_id=sample.client_id,
                t_s=sample.t_s,
                coverage_state=window.coverage_state,
                raw_backed=False,
                reason=coverage_reason,
            ),
        )
    window_i16 = _assemble_window_samples(sensor_data=sensor_data, segments=window.segments)
    if window_i16.shape[0] != fft_n:
        return (
            sample,
            RawReplayWindowCoverage(
                client_id=sample.client_id,
                t_s=sample.t_s,
                coverage_state="partial",
                raw_backed=False,
                reason="window_truncated",
            ),
        )
    window_f32 = window_i16.astype(np.float32, copy=True)
    if accel_scale_g_per_lsb is not None and accel_scale_g_per_lsb > 0:
        window_f32 *= np.float32(accel_scale_g_per_lsb)
    domain_strength = _compute_strength_metrics(
        window_f32,
        sample_rate_hz,
        fft_computer=fft_computer,
    )
    top_peaks = tuple(peak for peak in domain_strength.top_peaks if peak.is_valid)
    last_xyz = window_f32[-1]
    return (
        replace(
            sample,
            accel_x_g=float(last_xyz[0]),
            accel_y_g=float(last_xyz[1]),
            accel_z_g=float(last_xyz[2]),
            dominant_freq_hz=domain_strength.dominant_hz,
            top_peaks=top_peaks,
            vibration_strength_db=domain_strength.vibration_strength_db,
            strength_bucket=domain_strength.strength_bucket,
            strength_peak_amp_g=domain_strength.peak_amp_g,
            strength_floor_amp_g=domain_strength.noise_floor_amp_g,
        ),
        RawReplayWindowCoverage(
            client_id=sample.client_id,
            t_s=sample.t_s,
            coverage_state="complete",
            raw_backed=True,
            reason="timing_fallback" if window.timing_source == "legacy_t_s" else None,
        ),
    )


def _build_fft_computer(metadata: RunMetadata) -> SpectralAnalysisComputer:
    return SpectralAnalysisComputer(
        fft_n=int(metadata.fft_window_size_samples or 0),
        spectrum_min_hz=SPECTRUM_MIN_HZ,
        spectrum_max_hz=SPECTRUM_MAX_HZ,
    )


def _build_sensor_timeline(raw_capture: RawRunCapture, *, sensor_id: str) -> _SensorTimeline:
    sensor_data = raw_capture.sensor_data(sensor_id)
    if sensor_data is None:
        return _SensorTimeline(
            client_id=sensor_id,
            sample_rate_hz=0,
            sample_period_us=0.0,
            chunks=(),
            gap_intervals=(),
            overlap_intervals=(),
            run_start_monotonic_us=None,
            anchored=False,
        )
    sample_rate_hz = int(sensor_data.manifest.sample_rate_hz or 0)
    sample_period_us = 1_000_000.0 / float(sample_rate_hz) if sample_rate_hz > 0 else 0.0
    chunk_spans = tuple(
        _TimelineChunk(
            sample_start=int(chunk.sample_start),
            sample_end=int(chunk.sample_start + chunk.sample_count),
            start_us=float(chunk.t0_us),
            end_us=float(chunk.t0_us) + (float(chunk.sample_count) * sample_period_us),
        )
        for chunk in sorted(sensor_data.chunks, key=lambda chunk: (chunk.t0_us, chunk.sample_start))
        if chunk.sample_count > 0
    )
    if sample_rate_hz <= 0 or not chunk_spans:
        return _SensorTimeline(
            client_id=sensor_id,
            sample_rate_hz=sample_rate_hz,
            sample_period_us=sample_period_us,
            chunks=chunk_spans,
            gap_intervals=(),
            overlap_intervals=(),
            run_start_monotonic_us=raw_capture.manifest.run_start_monotonic_us,
            anchored=False,
        )
    gap_intervals: list[_TimelineInterval] = []
    overlap_intervals: list[_TimelineInterval] = []
    timing_tolerance_us = max(1.0, sample_period_us * _TIMING_TOLERANCE_SAMPLES)
    previous: _TimelineChunk | None = None
    for chunk in chunk_spans:
        if previous is not None:
            delta_us = chunk.start_us - previous.end_us
            if delta_us > timing_tolerance_us:
                gap_intervals.append(
                    _TimelineInterval(start_us=previous.end_us, end_us=chunk.start_us)
                )
            elif delta_us < -timing_tolerance_us:
                overlap_intervals.append(
                    _TimelineInterval(
                        start_us=chunk.start_us,
                        end_us=min(previous.end_us, chunk.end_us),
                    )
                )
        previous = chunk
    return _SensorTimeline(
        client_id=sensor_id,
        sample_rate_hz=sample_rate_hz,
        sample_period_us=sample_period_us,
        chunks=chunk_spans,
        gap_intervals=tuple(gap_intervals),
        overlap_intervals=tuple(overlap_intervals),
        run_start_monotonic_us=raw_capture.manifest.run_start_monotonic_us,
        anchored=raw_capture.manifest.run_start_monotonic_us is not None,
    )


def _resolve_window(
    *,
    timeline: _SensorTimeline,
    sample: SensorFrame,
    fft_n: int,
) -> _ResolvedWindow:
    if not timeline.anchored:
        return _ResolvedWindow(coverage_state="missing", reason="legacy_anchor_missing")
    if not timeline.chunks or timeline.sample_period_us <= 0:
        return _ResolvedWindow(coverage_state="missing", reason="raw_chunks_missing")
    requested_end_us, timing_source = _requested_end_us(timeline=timeline, sample=sample)
    if requested_end_us is None:
        return _ResolvedWindow(coverage_state="missing", reason="sample_time_missing")
    requested_start_us = requested_end_us - (float(fft_n) * timeline.sample_period_us)
    if requested_start_us < 0:
        return _ResolvedWindow(coverage_state="missing", reason="window_before_capture")
    if _intersects_intervals(
        timeline.gap_intervals,
        start_us=requested_start_us,
        end_us=requested_end_us,
        tolerance_us=timeline.timing_tolerance_us,
    ):
        return _ResolvedWindow(coverage_state="partial", reason="window_crosses_gap")
    if _intersects_intervals(
        timeline.overlap_intervals,
        start_us=requested_start_us,
        end_us=requested_end_us,
        tolerance_us=timeline.timing_tolerance_us,
    ):
        return _ResolvedWindow(coverage_state="partial", reason="window_crosses_overlap")
    first_chunk = timeline.chunks[0]
    last_chunk = timeline.chunks[-1]
    if requested_start_us < (first_chunk.start_us - timeline.timing_tolerance_us):
        return _ResolvedWindow(coverage_state="missing", reason="window_before_capture")
    if requested_end_us > (last_chunk.end_us + timeline.timing_tolerance_us):
        return _ResolvedWindow(coverage_state="missing", reason="window_after_capture")
    segments = _window_segments_for_time(
        timeline=timeline,
        requested_end_us=requested_end_us,
        sample_count=fft_n,
    )
    if not segments:
        return _ResolvedWindow(coverage_state="missing", reason="window_after_capture")
    return _ResolvedWindow(
        coverage_state="complete",
        reason=None,
        segments=segments,
        timing_source=timing_source,
    )


def _requested_end_us(
    *,
    timeline: _SensorTimeline,
    sample: SensorFrame,
) -> tuple[float | None, str]:
    run_start_monotonic_us = float(timeline.run_start_monotonic_us or 0)
    analysis_window_end_us = sample.analysis_window_end_us
    if analysis_window_end_us is not None:
        return run_start_monotonic_us + float(analysis_window_end_us), "explicit_window"
    if sample.t_s is None or not isfinite(sample.t_s) or sample.t_s <= 0:
        return None, "legacy_t_s"
    return run_start_monotonic_us + (float(sample.t_s) * 1_000_000.0), "legacy_t_s"


def _window_segments_for_time(
    *,
    timeline: _SensorTimeline,
    requested_end_us: float,
    sample_count: int,
) -> tuple[_WindowSegment, ...]:
    tolerance_us = timeline.timing_tolerance_us
    for chunk_index, chunk in enumerate(timeline.chunks):
        if requested_end_us < (chunk.start_us - tolerance_us):
            break
        if requested_end_us <= (chunk.end_us + tolerance_us):
            relative_samples = max(
                0,
                int(round((requested_end_us - chunk.start_us) / timeline.sample_period_us)),
            )
            return _collect_window_segments(
                timeline=timeline,
                end_chunk_index=chunk_index,
                end_offset=relative_samples,
                sample_count=sample_count,
            )
    return ()


def _collect_window_segments(
    *,
    timeline: _SensorTimeline,
    end_chunk_index: int,
    end_offset: int,
    sample_count: int,
) -> tuple[_WindowSegment, ...]:
    remaining = max(0, sample_count)
    chunk_index = end_chunk_index
    local_end = max(0, end_offset)
    segments: list[_WindowSegment] = []
    while remaining > 0 and chunk_index >= 0:
        chunk = timeline.chunks[chunk_index]
        chunk_length = max(0, chunk.sample_end - chunk.sample_start)
        clamped_end = min(chunk_length, local_end)
        if clamped_end > 0:
            take = min(remaining, clamped_end)
            raw_end = chunk.sample_start + clamped_end
            raw_start = raw_end - take
            segments.append(_WindowSegment(sample_start=raw_start, sample_end=raw_end))
            remaining -= take
        chunk_index -= 1
        if chunk_index >= 0:
            previous = timeline.chunks[chunk_index]
            local_end = max(0, previous.sample_end - previous.sample_start)
    if remaining > 0:
        return ()
    segments.reverse()
    return tuple(segments)


def _assemble_window_samples(
    *,
    sensor_data: RawCaptureSensorData,
    segments: tuple[_WindowSegment, ...],
) -> np.ndarray:
    if not segments:
        return np.empty((0, 3), dtype=np.int16)
    if len(segments) == 1:
        segment = segments[0]
        return sensor_data.samples_i16[segment.sample_start : segment.sample_end]
    return np.vstack(
        [sensor_data.samples_i16[segment.sample_start : segment.sample_end] for segment in segments]
    )


def _intersects_intervals(
    intervals: tuple[_TimelineInterval, ...],
    *,
    start_us: float,
    end_us: float,
    tolerance_us: float,
) -> bool:
    return any(
        interval.start_us < (end_us - tolerance_us) and interval.end_us > (start_us + tolerance_us)
        for interval in intervals
    )


def _replay_confidence(
    *,
    raw_backed_sample_count: int,
    replay_window_count: int,
    partial_window_count: int,
    missing_window_count: int,
    gap_count: int,
    overlap_count: int,
    dropped_chunk_count: int,
    sample_rate_mismatch_count: int,
    unanchored_sensor_count: int,
) -> RawReplayConfidence:
    if replay_window_count <= 0:
        return "unavailable"
    if raw_backed_sample_count <= 0:
        return "fallback"
    if (
        raw_backed_sample_count == replay_window_count
        and partial_window_count <= 0
        and missing_window_count <= 0
        and gap_count <= 0
        and overlap_count <= 0
        and dropped_chunk_count <= 0
        and sample_rate_mismatch_count <= 0
        and unanchored_sensor_count <= 0
    ):
        return "full"
    return "partial"


def _build_replay_warnings(
    *,
    raw_backed_sample_count: int,
    timing_fallback_count: int,
    partial_window_count: int,
    missing_window_count: int,
    gap_count: int,
    overlap_count: int,
    dropped_chunk_count: int,
    queue_overflow_chunk_count: int,
    invalid_chunk_count: int,
    write_error_chunk_count: int,
    sample_rate_mismatch_count: int,
    unanchored_sensor_count: int,
) -> tuple[RunContextWarning, ...]:
    if unanchored_sensor_count > 0 and raw_backed_sample_count <= 0:
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
    if dropped_chunk_count > 0:
        warnings.append(
            RunContextWarning(
                code=WARNING_CODE_RAW_REPLAY_DROPPED_CHUNKS,
                severity="warn",
                applies_to="raw_replay",
                title=i18n_ref("RUN_CONTEXT_WARNING_RAW_REPLAY_DROPPED_CHUNKS_TITLE"),
                detail=i18n_ref(
                    "RUN_CONTEXT_WARNING_RAW_REPLAY_DROPPED_CHUNKS_DETAIL",
                    count=str(max(0, dropped_chunk_count)),
                    queue_overflow=str(max(0, queue_overflow_chunk_count)),
                    invalid=str(max(0, invalid_chunk_count)),
                    write_errors=str(max(0, write_error_chunk_count)),
                ),
            )
        )
    if (
        partial_window_count <= 0
        and missing_window_count <= 0
        and gap_count <= 0
        and overlap_count <= 0
        and sample_rate_mismatch_count <= 0
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
            ),
        )
    )
    return tuple(warnings)


def _compute_strength_metrics(
    window_f32: np.ndarray,
    sample_rate_hz: int,
    *,
    fft_computer: SpectralAnalysisComputer,
) -> StrengthMetrics:
    if window_f32.size <= 0:
        return strength_metrics_from_mapping(None)
    fft_result = fft_computer.compute_fft_spectrum(
        medfilt3(window_f32.T),
        sample_rate_hz,
        spike_filter_enabled=False,
    )
    return strength_metrics_from_mapping(fft_result["strength_metrics"])
