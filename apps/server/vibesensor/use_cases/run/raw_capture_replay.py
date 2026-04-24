"""Raw-capture replay helpers for post-stop analysis."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from typing import Literal

import numpy as np

from vibesensor.domain.strength_metrics import StrengthMetrics
from vibesensor.shared.boundaries.codecs import strength_metrics_from_mapping
from vibesensor.shared.constants.dsp import SPECTRUM_MAX_HZ, SPECTRUM_MIN_HZ
from vibesensor.shared.json_utils import i18n_ref
from vibesensor.shared.run_context_warning import (
    WARNING_CODE_RAW_REPLAY_COVERAGE_INCOMPLETE,
    WARNING_CODE_RAW_REPLAY_LEGACY_FALLBACK,
    RunContextWarning,
)
from vibesensor.shared.types.raw_capture import RawRunCapture
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame
from vibesensor.vibration_strength import combined_spectrum_amp_g, compute_vibration_strength_db

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
    sample_end: int | None = None


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
    replayed: list[SensorFrame] = []
    coverages: list[RawReplayWindowCoverage] = []
    complete_window_count = 0
    partial_window_count = 0
    missing_window_count = 0
    sample_rate_mismatch_count = 0
    raw_backed_count = 0
    scale = metadata.accel_scale_g_per_lsb
    for sample in samples:
        rebuilt, coverage = _rebuild_sample(
            sample=sample,
            timeline=timelines.get(sample.client_id),
            raw_capture=raw_capture,
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
        replayed.append(rebuilt)
        coverages.append(coverage)
    gap_count = sum(len(timeline.gap_intervals) for timeline in timelines.values())
    overlap_count = sum(len(timeline.overlap_intervals) for timeline in timelines.values())
    unanchored_sensor_count = sum(1 for timeline in timelines.values() if not timeline.anchored)
    replay_confidence = _replay_confidence(
        raw_backed_sample_count=raw_backed_count,
        replay_window_count=len(samples),
        partial_window_count=partial_window_count,
        missing_window_count=missing_window_count,
        gap_count=gap_count,
        overlap_count=overlap_count,
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
            dropped_chunk_count=0,
            sample_rate_mismatch_count=sample_rate_mismatch_count,
            unanchored_sensor_count=unanchored_sensor_count,
            replay_confidence=replay_confidence,
            raw_capture_mode=raw_capture_mode,
            warnings=_build_replay_warnings(
                raw_backed_sample_count=raw_backed_count,
                partial_window_count=partial_window_count,
                missing_window_count=missing_window_count,
                gap_count=gap_count,
                overlap_count=overlap_count,
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
    if window.coverage_state != "complete" or window.sample_end is None:
        return (
            sample,
            RawReplayWindowCoverage(
                client_id=sample.client_id,
                t_s=sample.t_s,
                coverage_state=window.coverage_state,
                raw_backed=False,
                reason=window.reason,
            ),
        )
    window_i16 = sensor_data.samples_i16[window.sample_end - fft_n : window.sample_end]
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
    domain_strength = _compute_strength_metrics(window_f32, sample_rate_hz)
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
        ),
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
    if sample.t_s is None or not isfinite(sample.t_s) or sample.t_s <= 0:
        return _ResolvedWindow(coverage_state="missing", reason="sample_time_missing")
    run_start_monotonic_us = float(timeline.run_start_monotonic_us or 0)
    requested_end_us = run_start_monotonic_us + (float(sample.t_s) * 1_000_000.0)
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
    sample_end = _sample_end_for_time(
        timeline=timeline,
        requested_end_us=requested_end_us,
    )
    if sample_end is None or sample_end < fft_n:
        return _ResolvedWindow(coverage_state="missing", reason="window_after_capture")
    return _ResolvedWindow(coverage_state="complete", reason=None, sample_end=sample_end)


def _sample_end_for_time(
    *,
    timeline: _SensorTimeline,
    requested_end_us: float,
) -> int | None:
    tolerance_us = timeline.timing_tolerance_us
    for chunk in timeline.chunks:
        if requested_end_us < (chunk.start_us - tolerance_us):
            break
        if requested_end_us <= (chunk.end_us + tolerance_us):
            relative_samples = int(
                round((requested_end_us - chunk.start_us) / timeline.sample_period_us)
            )
            return max(
                chunk.sample_start, min(chunk.sample_end, chunk.sample_start + relative_samples)
            )
    return None


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
        and sample_rate_mismatch_count <= 0
        and unanchored_sensor_count <= 0
    ):
        return "full"
    return "partial"


def _build_replay_warnings(
    *,
    raw_backed_sample_count: int,
    partial_window_count: int,
    missing_window_count: int,
    gap_count: int,
    overlap_count: int,
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
    if (
        partial_window_count <= 0
        and missing_window_count <= 0
        and gap_count <= 0
        and overlap_count <= 0
        and sample_rate_mismatch_count <= 0
    ):
        return ()
    return (
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
        ),
    )


def _compute_strength_metrics(window_f32: np.ndarray, sample_rate_hz: int) -> StrengthMetrics:
    axes_by_time = window_f32.T
    detrended = axes_by_time - np.mean(axes_by_time, axis=1, keepdims=True, dtype=np.float32)
    fft_window = np.asarray(np.hanning(window_f32.shape[0]), dtype=np.float32)
    if fft_window.size <= 0:
        return strength_metrics_from_mapping(None)
    scale = float(2.0 / max(1.0, float(np.sum(fft_window))))
    transformed = np.fft.rfft(detrended * fft_window, axis=1)
    freqs = np.fft.rfftfreq(window_f32.shape[0], d=1.0 / sample_rate_hz)
    valid = (freqs >= SPECTRUM_MIN_HZ) & (freqs <= SPECTRUM_MAX_HZ)
    if not np.any(valid):
        return strength_metrics_from_mapping(None)
    axis_spectra = np.abs(transformed[:, valid]).astype(np.float64, copy=False) * scale
    combined = np.asarray(
        combined_spectrum_amp_g(axis_spectra_amp_g=axis_spectra, axis_count_for_mean=3),
        dtype=np.float64,
    )
    raw_strength = compute_vibration_strength_db(
        freq_hz=freqs[valid],
        combined_spectrum_amp_g_values=combined,
    )
    return strength_metrics_from_mapping(raw_strength)
