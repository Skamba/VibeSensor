"""Shared raw-capture timeline alignment helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from vibesensor.shared.types.raw_capture import (
    RawCaptureSensorClockSync,
    RawCaptureSensorData,
    RawRunCapture,
)

type RawTimelineCoverageState = Literal["complete", "partial", "missing"]

_TIMING_TOLERANCE_SAMPLES = 0.75

__all__ = [
    "RawSensorTimeline",
    "RawTimelineChunk",
    "RawTimelineInterval",
    "RawTimelineWindow",
    "RawWindowSegment",
    "assemble_raw_window_samples",
    "build_raw_sensor_timeline",
    "raw_anchor_reason",
    "raw_timeline_has_unverified_sync",
    "raw_timeline_is_legacy",
    "resolve_raw_window_end_time",
]


@dataclass(frozen=True, slots=True)
class RawTimelineInterval:
    start_us: float
    end_us: float


@dataclass(frozen=True, slots=True)
class RawTimelineChunk:
    """Chronological chunk timing plus append-order raw-buffer offsets."""

    sample_start: int
    sample_end: int
    start_us: float
    end_us: float


@dataclass(frozen=True, slots=True)
class RawSensorTimeline:
    client_id: str
    sample_rate_hz: int
    sample_period_us: float
    chunks: tuple[RawTimelineChunk, ...]
    gap_intervals: tuple[RawTimelineInterval, ...]
    overlap_intervals: tuple[RawTimelineInterval, ...]
    run_start_monotonic_us: int | None
    anchored: bool
    anchor_reason: str | None
    clock_sync: RawCaptureSensorClockSync | None = None

    @property
    def timing_tolerance_us(self) -> float:
        return max(1.0, self.sample_period_us * _TIMING_TOLERANCE_SAMPLES)


@dataclass(frozen=True, slots=True)
class RawWindowSegment:
    sample_start: int
    sample_end: int


@dataclass(frozen=True, slots=True)
class RawTimelineWindow:
    coverage_state: RawTimelineCoverageState
    reason: str | None
    segments: tuple[RawWindowSegment, ...] = ()
    timing_source: str = "explicit_window"


def build_raw_sensor_timeline(
    raw_capture: RawRunCapture,
    *,
    sensor_id: str,
) -> RawSensorTimeline:
    sensor_data = raw_capture.sensor_data(sensor_id)
    if sensor_data is None:
        return RawSensorTimeline(
            client_id=sensor_id,
            sample_rate_hz=0,
            sample_period_us=0.0,
            chunks=(),
            gap_intervals=(),
            overlap_intervals=(),
            run_start_monotonic_us=raw_capture.manifest.run_start_monotonic_us,
            anchored=False,
            anchor_reason="sensor_missing",
        )
    sample_rate_hz = int(sensor_data.manifest.sample_rate_hz)
    sample_period_us = 1_000_000.0 / float(sample_rate_hz) if sample_rate_hz > 0 else 0.0
    chunk_spans = tuple(
        RawTimelineChunk(
            sample_start=int(chunk.sample_start),
            sample_end=int(chunk.sample_start + chunk.sample_count),
            start_us=float(chunk.t0_us),
            end_us=float(chunk.t0_us) + (float(chunk.sample_count) * sample_period_us),
        )
        for chunk in sorted(sensor_data.chunks, key=lambda chunk: (chunk.t0_us, chunk.sample_start))
        if chunk.sample_count > 0
    )
    if not chunk_spans:
        return RawSensorTimeline(
            client_id=sensor_id,
            sample_rate_hz=sample_rate_hz,
            sample_period_us=sample_period_us,
            chunks=chunk_spans,
            gap_intervals=(),
            overlap_intervals=(),
            run_start_monotonic_us=raw_capture.manifest.run_start_monotonic_us,
            anchored=False,
            anchor_reason="raw_chunks_missing",
            clock_sync=sensor_data.manifest.clock_sync,
        )
    gap_intervals: list[RawTimelineInterval] = []
    overlap_intervals: list[RawTimelineInterval] = []
    timing_tolerance_us = max(1.0, sample_period_us * _TIMING_TOLERANCE_SAMPLES)
    previous: RawTimelineChunk | None = None
    for chunk in chunk_spans:
        if previous is not None:
            delta_us = chunk.start_us - previous.end_us
            if delta_us > timing_tolerance_us:
                gap_intervals.append(
                    RawTimelineInterval(start_us=previous.end_us, end_us=chunk.start_us)
                )
            elif delta_us < -timing_tolerance_us:
                overlap_intervals.append(
                    RawTimelineInterval(
                        start_us=chunk.start_us,
                        end_us=min(previous.end_us, chunk.end_us),
                    )
                )
        previous = chunk
    return RawSensorTimeline(
        client_id=sensor_id,
        sample_rate_hz=sample_rate_hz,
        sample_period_us=sample_period_us,
        chunks=chunk_spans,
        gap_intervals=tuple(gap_intervals),
        overlap_intervals=tuple(overlap_intervals),
        run_start_monotonic_us=raw_capture.manifest.run_start_monotonic_us,
        anchored=(
            raw_capture.manifest.run_start_monotonic_us is not None
            and sensor_data.manifest.clock_sync is not None
            and sensor_data.manifest.clock_sync.verified
        ),
        anchor_reason=raw_anchor_reason(
            run_start_monotonic_us=raw_capture.manifest.run_start_monotonic_us,
            clock_sync=sensor_data.manifest.clock_sync,
        ),
        clock_sync=sensor_data.manifest.clock_sync,
    )


def resolve_raw_window_end_time(
    *,
    timeline: RawSensorTimeline,
    requested_end_us: float,
    sample_count: int,
    timing_source: str = "explicit_window",
) -> RawTimelineWindow:
    if not timeline.anchored:
        return RawTimelineWindow(
            coverage_state="missing",
            reason=timeline.anchor_reason or "legacy_anchor_missing",
        )
    if not timeline.chunks or timeline.sample_period_us <= 0:
        return RawTimelineWindow(coverage_state="missing", reason="raw_chunks_missing")
    requested_start_us = requested_end_us - (float(sample_count) * timeline.sample_period_us)
    if requested_start_us < 0:
        return RawTimelineWindow(coverage_state="missing", reason="window_before_capture")
    if _intersects_intervals(
        timeline.gap_intervals,
        start_us=requested_start_us,
        end_us=requested_end_us,
        tolerance_us=timeline.timing_tolerance_us,
    ):
        return RawTimelineWindow(coverage_state="partial", reason="window_crosses_gap")
    if _intersects_intervals(
        timeline.overlap_intervals,
        start_us=requested_start_us,
        end_us=requested_end_us,
        tolerance_us=timeline.timing_tolerance_us,
    ):
        return RawTimelineWindow(coverage_state="partial", reason="window_crosses_overlap")
    first_chunk = timeline.chunks[0]
    last_chunk = timeline.chunks[-1]
    if requested_start_us < (first_chunk.start_us - timeline.timing_tolerance_us):
        return RawTimelineWindow(coverage_state="missing", reason="window_before_capture")
    if requested_end_us > (last_chunk.end_us + timeline.timing_tolerance_us):
        return RawTimelineWindow(coverage_state="missing", reason="window_after_capture")
    segments = _window_segments_for_time(
        timeline=timeline,
        requested_end_us=requested_end_us,
        sample_count=sample_count,
    )
    if not segments:
        return RawTimelineWindow(coverage_state="missing", reason="window_after_capture")
    return RawTimelineWindow(
        coverage_state="complete",
        reason=None,
        segments=segments,
        timing_source=timing_source,
    )


def assemble_raw_window_samples(
    *,
    sensor_data: RawCaptureSensorData,
    segments: tuple[RawWindowSegment, ...],
) -> np.ndarray:
    if not segments:
        return np.empty((0, 3), dtype=np.int16)
    if len(segments) == 1:
        segment = segments[0]
        return sensor_data.samples_i16[segment.sample_start : segment.sample_end]
    return np.vstack(
        [sensor_data.samples_i16[segment.sample_start : segment.sample_end] for segment in segments]
    )


def raw_anchor_reason(
    *,
    run_start_monotonic_us: int | None,
    clock_sync: RawCaptureSensorClockSync | None,
) -> str:
    if run_start_monotonic_us is None or clock_sync is None:
        return "legacy_anchor_missing"
    if clock_sync.proof_state == "verified":
        return "anchor_verified"
    return f"clock_sync_{clock_sync.proof_state}"


def raw_timeline_is_legacy(timeline: RawSensorTimeline) -> bool:
    return timeline.run_start_monotonic_us is None or timeline.clock_sync is None


def raw_timeline_has_unverified_sync(timeline: RawSensorTimeline) -> bool:
    return (
        timeline.clock_sync is not None
        and not timeline.clock_sync.verified
        and timeline.run_start_monotonic_us is not None
    )


def _window_segments_for_time(
    *,
    timeline: RawSensorTimeline,
    requested_end_us: float,
    sample_count: int,
) -> tuple[RawWindowSegment, ...]:
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
    timeline: RawSensorTimeline,
    end_chunk_index: int,
    end_offset: int,
    sample_count: int,
) -> tuple[RawWindowSegment, ...]:
    remaining = max(0, sample_count)
    chunk_index = end_chunk_index
    local_end = max(0, end_offset)
    segments: list[RawWindowSegment] = []
    while remaining > 0 and chunk_index >= 0:
        chunk = timeline.chunks[chunk_index]
        chunk_length = max(0, chunk.sample_end - chunk.sample_start)
        clamped_end = min(chunk_length, local_end)
        if clamped_end > 0:
            take = min(remaining, clamped_end)
            raw_end = chunk.sample_start + clamped_end
            raw_start = raw_end - take
            segments.append(RawWindowSegment(sample_start=raw_start, sample_end=raw_end))
            remaining -= take
        chunk_index -= 1
        if chunk_index >= 0:
            previous = timeline.chunks[chunk_index]
            local_end = max(0, previous.sample_end - previous.sample_start)
    if remaining > 0:
        return ()
    segments.reverse()
    return tuple(segments)


def _intersects_intervals(
    intervals: tuple[RawTimelineInterval, ...],
    *,
    start_us: float,
    end_us: float,
    tolerance_us: float,
) -> bool:
    return any(
        interval.start_us < (end_us - tolerance_us) and interval.end_us > (start_us + tolerance_us)
        for interval in intervals
    )
