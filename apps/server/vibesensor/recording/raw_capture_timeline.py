"""Shared raw-capture timeline alignment helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt

from vibesensor.recording.raw_capture import (
    RawCaptureSensorClockSync,
    RawCaptureSensorData,
    RawRunCapture,
)

type FloatArray = npt.NDArray[np.float64]
type IntArray = npt.NDArray[np.int64]
type RawTimelineCoverageState = Literal["complete", "partial", "missing"]

_TIMING_TOLERANCE_SAMPLES = 0.75

__all__ = [
    "RawSensorTimeline",
    "RawTimelineChunks",
    "RawTimelineIntervals",
    "RawTimelineWindow",
    "RawWindowSegment",
    "assemble_raw_window_samples",
    "build_raw_sensor_timeline",
    "raw_anchor_reason",
    "raw_timeline_has_unverified_sync",
    "raw_timeline_is_legacy",
    "resolve_raw_window_end_time",
]


@dataclass(frozen=True, slots=True, eq=False)
class RawTimelineIntervals:
    """Gap or overlap intervals in chunk order: starts never decrease.

    ``end_reach_us`` is the running maximum of the interval ends, so whether any
    interval overlaps a window is one binary search instead of a scan.
    """

    start_us: FloatArray
    end_us: FloatArray
    end_reach_us: FloatArray

    def __len__(self) -> int:
        return int(self.start_us.shape[0])

    def intersects(self, *, start_us: float, end_us: float, tolerance_us: float) -> bool:
        """Whether any interval starts before ``end - tol`` and ends after ``start + tol``."""
        before_end = int(np.searchsorted(self.start_us, end_us - tolerance_us, side="left"))
        return before_end > 0 and bool(self.end_reach_us[before_end - 1] > start_us + tolerance_us)


@dataclass(frozen=True, slots=True, eq=False)
class RawTimelineChunks:
    """Chronological chunk timing plus append-order raw-buffer offsets, as columns.

    ``end_reach_us`` (running maximum of ``end_us + tolerance``) and
    ``start_floor_us`` (``start_us - tolerance``) never decrease, so locating the
    chunk a window ends in is a binary search.
    """

    sample_start: IntArray
    sample_end: IntArray
    start_us: FloatArray
    end_us: FloatArray
    end_reach_us: FloatArray
    start_floor_us: FloatArray

    def __len__(self) -> int:
        return int(self.start_us.shape[0])

    def window_end_chunk_index(self, requested_end_us: float) -> int | None:
        """The first chunk (in time order) the window end falls in, within tolerance.

        ``None`` when the end lies before that chunk's start, past every chunk, or
        before the first chunk.
        """
        first_reaching = int(np.searchsorted(self.end_reach_us, requested_end_us, side="left"))
        first_after = int(np.searchsorted(self.start_floor_us, requested_end_us, side="right"))
        if first_reaching >= len(self) or first_after <= first_reaching:
            return None
        return first_reaching


@dataclass(frozen=True, slots=True)
class RawSensorTimeline:
    client_id: str
    sample_rate_hz: int
    sample_period_us: float
    chunks: RawTimelineChunks
    gap_intervals: RawTimelineIntervals
    overlap_intervals: RawTimelineIntervals
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
            chunks=_timeline_chunks(sensor_data=None, sample_period_us=0.0, tolerance_us=0.0),
            gap_intervals=_EMPTY_INTERVALS,
            overlap_intervals=_EMPTY_INTERVALS,
            run_start_monotonic_us=raw_capture.manifest.run_start_monotonic_us,
            anchored=False,
            anchor_reason="sensor_missing",
        )
    sample_rate_hz = int(sensor_data.manifest.sample_rate_hz)
    sample_period_us = 1_000_000.0 / float(sample_rate_hz) if sample_rate_hz > 0 else 0.0
    timing_tolerance_us = max(1.0, sample_period_us * _TIMING_TOLERANCE_SAMPLES)
    chunks = _timeline_chunks(
        sensor_data=sensor_data,
        sample_period_us=sample_period_us,
        tolerance_us=timing_tolerance_us,
    )
    if len(chunks) == 0:
        return RawSensorTimeline(
            client_id=sensor_id,
            sample_rate_hz=sample_rate_hz,
            sample_period_us=sample_period_us,
            chunks=chunks,
            gap_intervals=_EMPTY_INTERVALS,
            overlap_intervals=_EMPTY_INTERVALS,
            run_start_monotonic_us=raw_capture.manifest.run_start_monotonic_us,
            anchored=False,
            anchor_reason="raw_chunks_missing",
            clock_sync=sensor_data.manifest.clock_sync,
        )
    previous_end_us = chunks.end_us[:-1]
    current_start_us = chunks.start_us[1:]
    delta_us = current_start_us - previous_end_us
    gaps = delta_us > timing_tolerance_us
    overlaps = delta_us < -timing_tolerance_us
    return RawSensorTimeline(
        client_id=sensor_id,
        sample_rate_hz=sample_rate_hz,
        sample_period_us=sample_period_us,
        chunks=chunks,
        gap_intervals=_intervals(previous_end_us[gaps], current_start_us[gaps]),
        overlap_intervals=_intervals(
            current_start_us[overlaps],
            np.minimum(previous_end_us[overlaps], chunks.end_us[1:][overlaps]),
        ),
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


def _timeline_chunks(
    *,
    sensor_data: RawCaptureSensorData | None,
    sample_period_us: float,
    tolerance_us: float,
) -> RawTimelineChunks:
    if sensor_data is None:
        sample_start = np.empty(0, dtype=np.int64)
        sample_count = np.empty(0, dtype=np.int64)
        t0_us = np.empty(0, dtype=np.int64)
    else:
        table = sensor_data.chunks
        # Chronological; ties keep append order. Empty chunks carry no samples.
        order = np.lexsort((table.sample_start, table.t0_us))
        order = order[table.sample_count[order] > 0]
        sample_start = table.sample_start[order]
        sample_count = table.sample_count[order]
        t0_us = table.t0_us[order]
    start_us = t0_us.astype(np.float64)
    end_us = start_us + (sample_count.astype(np.float64) * sample_period_us)
    return RawTimelineChunks(
        sample_start=sample_start,
        sample_end=sample_start + sample_count,
        start_us=start_us,
        end_us=end_us,
        end_reach_us=np.maximum.accumulate(end_us + tolerance_us) if end_us.size else end_us,
        start_floor_us=start_us - tolerance_us,
    )


def _intervals(start_us: FloatArray, end_us: FloatArray) -> RawTimelineIntervals:
    return RawTimelineIntervals(
        start_us=start_us,
        end_us=end_us,
        end_reach_us=np.maximum.accumulate(end_us) if end_us.size else end_us,
    )


_EMPTY_INTERVALS = _intervals(np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64))


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
    if len(timeline.chunks) == 0 or timeline.sample_period_us <= 0:
        return RawTimelineWindow(coverage_state="missing", reason="raw_chunks_missing")
    requested_start_us = requested_end_us - (float(sample_count) * timeline.sample_period_us)
    if requested_start_us < 0:
        return RawTimelineWindow(coverage_state="missing", reason="window_before_capture")
    if timeline.gap_intervals.intersects(
        start_us=requested_start_us,
        end_us=requested_end_us,
        tolerance_us=timeline.timing_tolerance_us,
    ):
        return RawTimelineWindow(coverage_state="partial", reason="window_crosses_gap")
    if timeline.overlap_intervals.intersects(
        start_us=requested_start_us,
        end_us=requested_end_us,
        tolerance_us=timeline.timing_tolerance_us,
    ):
        return RawTimelineWindow(coverage_state="partial", reason="window_crosses_overlap")
    chunks = timeline.chunks
    if requested_start_us < (float(chunks.start_us[0]) - timeline.timing_tolerance_us):
        return RawTimelineWindow(coverage_state="missing", reason="window_before_capture")
    if requested_end_us > (float(chunks.end_us[-1]) + timeline.timing_tolerance_us):
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
    chunks = timeline.chunks
    end_chunk_index = chunks.window_end_chunk_index(requested_end_us)
    if end_chunk_index is None:
        return ()
    relative_samples = max(
        0,
        int(
            round(
                (requested_end_us - float(chunks.start_us[end_chunk_index]))
                / timeline.sample_period_us
            )
        ),
    )
    return _collect_window_segments(
        chunks=chunks,
        end_chunk_index=end_chunk_index,
        end_offset=relative_samples,
        sample_count=sample_count,
    )


def _collect_window_segments(
    *,
    chunks: RawTimelineChunks,
    end_chunk_index: int,
    end_offset: int,
    sample_count: int,
) -> tuple[RawWindowSegment, ...]:
    remaining = max(0, sample_count)
    chunk_index = end_chunk_index
    local_end = max(0, end_offset)
    segments: list[RawWindowSegment] = []
    while remaining > 0 and chunk_index >= 0:
        chunk_sample_start = int(chunks.sample_start[chunk_index])
        chunk_length = max(0, int(chunks.sample_end[chunk_index]) - chunk_sample_start)
        clamped_end = min(chunk_length, local_end)
        if clamped_end > 0:
            take = min(remaining, clamped_end)
            raw_end = chunk_sample_start + clamped_end
            raw_start = raw_end - take
            segments.append(RawWindowSegment(sample_start=raw_start, sample_end=raw_end))
            remaining -= take
        chunk_index -= 1
        if chunk_index >= 0:
            local_end = max(
                0, int(chunks.sample_end[chunk_index]) - int(chunks.sample_start[chunk_index])
            )
    if remaining > 0:
        return ()
    segments.reverse()
    return tuple(segments)
