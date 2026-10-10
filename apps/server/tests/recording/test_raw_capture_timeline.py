"""Raw-capture timeline lookups: binary search must agree with a plain scan.

Locating the chunk a window ends in, and whether the window crosses a gap or an
overlap, are binary searches over column arrays. The reference below is the
straightforward scan over every chunk and interval that they replace; the two
must give the same window for every request on gappy, overlapping and
out-of-order timelines. So must the lookup of many windows at once
(``contiguous_raw_window_starts``) wherever it finds a window in one slice.
"""

from __future__ import annotations

import random

import numpy as np
import pytest
from test_support.raw_capture_fixtures import verified_clock_sync

from vibesensor.recording.raw_capture import (
    RawCaptureChunkIndex,
    RawCaptureChunkTable,
    RawCaptureManifest,
    RawCaptureSensorData,
    RawCaptureSensorManifest,
    RawRunCapture,
)
from vibesensor.recording.raw_capture_timeline import (
    RawTimelineWindow,
    RawWindowSegment,
    build_raw_sensor_timeline,
    contiguous_raw_window_starts,
    resolve_raw_window_end_time,
)

_RATE_HZ = 800
_PERIOD_US = 1_000_000.0 / _RATE_HZ
_TOL_US = max(1.0, _PERIOD_US * 0.75)

type _Chunk = tuple[int, int, float, float]  # sample_start, sample_end, start_us, end_us
type _Interval = tuple[float, float]


def _reference_timeline(
    rows: list[RawCaptureChunkIndex],
) -> tuple[list[_Chunk], list[_Interval], list[_Interval]]:
    chunks = [
        (
            row.sample_start,
            row.sample_start + row.sample_count,
            float(row.t0_us),
            float(row.t0_us) + float(row.sample_count) * _PERIOD_US,
        )
        for row in sorted(rows, key=lambda row: (row.t0_us, row.sample_start))
        if row.sample_count > 0
    ]
    gaps: list[_Interval] = []
    overlaps: list[_Interval] = []
    for previous, chunk in zip(chunks, chunks[1:], strict=False):
        delta_us = chunk[2] - previous[3]
        if delta_us > _TOL_US:
            gaps.append((previous[3], chunk[2]))
        elif delta_us < -_TOL_US:
            overlaps.append((chunk[2], min(previous[3], chunk[3])))
    return chunks, gaps, overlaps


def _reference_window(
    chunks: list[_Chunk],
    gaps: list[_Interval],
    overlaps: list[_Interval],
    *,
    requested_end_us: float,
    sample_count: int,
) -> tuple[str, str | None, tuple[RawWindowSegment, ...]]:
    requested_start_us = requested_end_us - float(sample_count) * _PERIOD_US
    if requested_start_us < 0:
        return ("missing", "window_before_capture", ())
    for intervals, reason in ((gaps, "window_crosses_gap"), (overlaps, "window_crosses_overlap")):
        if any(
            start < requested_end_us - _TOL_US and end > requested_start_us + _TOL_US
            for start, end in intervals
        ):
            return ("partial", reason, ())
    if requested_start_us < chunks[0][2] - _TOL_US:
        return ("missing", "window_before_capture", ())
    if requested_end_us > chunks[-1][3] + _TOL_US:
        return ("missing", "window_after_capture", ())
    for end_index, (_, _, start_us, end_us) in enumerate(chunks):
        if requested_end_us < start_us - _TOL_US:
            break
        if requested_end_us <= end_us + _TOL_US:
            local_end = max(0, int(round((requested_end_us - start_us) / _PERIOD_US)))
            segments = _reference_segments(chunks, end_index, local_end, sample_count)
            if segments:
                return ("complete", None, segments)
            break
    return ("missing", "window_after_capture", ())


def _reference_segments(
    chunks: list[_Chunk], chunk_index: int, local_end: int, sample_count: int
) -> tuple[RawWindowSegment, ...]:
    remaining = sample_count
    segments: list[RawWindowSegment] = []
    while remaining > 0 and chunk_index >= 0:
        sample_start, sample_end, _, _ = chunks[chunk_index]
        clamped_end = min(sample_end - sample_start, local_end)
        if clamped_end > 0:
            take = min(remaining, clamped_end)
            segments.append(
                RawWindowSegment(
                    sample_start=sample_start + clamped_end - take,
                    sample_end=sample_start + clamped_end,
                )
            )
            remaining -= take
        chunk_index -= 1
        if chunk_index >= 0:
            local_end = chunks[chunk_index][1] - chunks[chunk_index][0]
    return () if remaining > 0 else tuple(reversed(segments))


def _gappy_chunk_rows(rng: random.Random) -> list[RawCaptureChunkIndex]:
    """Back-to-back chunks with drops, jitter, overlaps, empty chunks and shuffled order."""
    rows: list[RawCaptureChunkIndex] = []
    sample_start = 0
    t0_us = rng.randint(0, 50_000)
    for _ in range(rng.randint(1, 60)):
        sample_count = rng.choice((0, 1, 16, 64, 64, 64, 200))
        roll = rng.random()
        if roll < 0.15:
            t0_us += rng.randint(2_000, 400_000)  # dropped chunks: a gap
        elif roll < 0.3:
            t0_us -= rng.randint(1_000, 120_000)  # clock step back: an overlap
        elif roll < 0.4:
            t0_us += rng.randint(-1, 1)  # jitter inside the tolerance
        rows.append(
            RawCaptureChunkIndex(
                sample_start=sample_start,
                sample_count=sample_count,
                t0_us=max(0, t0_us),
                byte_offset=sample_start * 6,
            )
        )
        sample_start += sample_count
        t0_us += round(sample_count * _PERIOD_US)
    if rng.random() < 0.5:
        rng.shuffle(rows)  # the index is read in append order, not time order
    return rows


def _capture(rows: list[RawCaptureChunkIndex]) -> RawRunCapture:
    total = sum(row.sample_count for row in rows)
    sensor = RawCaptureSensorManifest(
        client_id="s1",
        sample_rate_hz=_RATE_HZ,
        data_file="s1.i16",
        index_file="s1.jsonl",
        sample_count=total,
        chunk_count=len(rows),
        bytes_written=total * 6,
        clock_sync=verified_clock_sync(),
    )
    manifest = RawCaptureManifest(
        run_id="run-timeline",
        relative_dir="run-timeline",
        sensors=(sensor,),
        total_samples=total,
        total_bytes=total * 6,
        created_at="2026-01-01T00:00:00Z",
        run_start_monotonic_us=0,
    )
    return RawRunCapture(
        manifest=manifest,
        sensors=(
            RawCaptureSensorData(
                manifest=sensor,
                samples_i16=np.zeros((total, 3), dtype=np.int16),
                chunks=RawCaptureChunkTable.from_rows(rows),
            ),
        ),
    )


def _requested_ends(chunks: list[_Chunk], rng: random.Random) -> list[float]:
    """Ends on, just inside and just outside every chunk edge, plus random points."""
    ends: list[float] = []
    for _, _, start_us, end_us in chunks:
        for edge in (start_us, end_us):
            ends.extend(edge + offset for offset in (-_TOL_US - 1.0, -_TOL_US, 0.0, _TOL_US, 3.3))
    last_us = chunks[-1][3] if chunks else 1_000.0
    ends.extend(rng.uniform(-1_000.0, last_us + 5_000.0) for _ in range(40))
    return ends


@pytest.mark.parametrize("seed", range(60))
def test_window_lookup_matches_a_full_scan_on_gappy_timelines(seed: int) -> None:
    rng = random.Random(seed)
    rows = _gappy_chunk_rows(rng)
    chunks, gaps, overlaps = _reference_timeline(rows)

    timeline = build_raw_sensor_timeline(_capture(rows), sensor_id="s1")

    for intervals, expected in (
        (timeline.gap_intervals, gaps),
        (timeline.overlap_intervals, overlaps),
    ):
        assert list(zip(intervals.start_us.tolist(), intervals.end_us.tolist(), strict=True)) == (
            expected
        )
    if not chunks:
        assert not timeline.anchored
        return
    requested_ends = _requested_ends(chunks, rng)
    for sample_count in (1, 64, 256):
        raw_starts = contiguous_raw_window_starts(
            timeline=timeline,
            requested_end_us=np.array(requested_ends, dtype=np.float64),
            sample_count=sample_count,
        ).tolist()
        for requested_end_us, raw_start in zip(requested_ends, raw_starts, strict=True):
            window: RawTimelineWindow = resolve_raw_window_end_time(
                timeline=timeline,
                requested_end_us=requested_end_us,
                sample_count=sample_count,
            )
            expected = _reference_window(
                chunks,
                gaps,
                overlaps,
                requested_end_us=requested_end_us,
                sample_count=sample_count,
            )
            assert (window.coverage_state, window.reason, window.segments) == expected, (
                requested_end_us,
                sample_count,
            )
            # At once: where the window starts when it is complete and one slice.
            assert raw_start == _one_slice_start(expected[2]), (requested_end_us, sample_count)


def _one_slice_start(segments: tuple[RawWindowSegment, ...]) -> int:
    """Where *segments* start in the raw buffer when they follow on there; -1 otherwise."""
    follow_on = all(
        segment.sample_end == following.sample_start
        for segment, following in zip(segments, segments[1:], strict=False)
    )
    return segments[0].sample_start if segments and follow_on else -1


def test_the_generated_timelines_exercise_every_outcome() -> None:
    outcomes: set[tuple[str, str | None]] = set()
    for seed in range(60):
        rng = random.Random(seed)
        chunks, gaps, overlaps = _reference_timeline(_gappy_chunk_rows(rng))
        if not chunks:
            continue
        for requested_end_us in _requested_ends(chunks, rng):
            for sample_count in (1, 64, 256):
                state, reason, segments = _reference_window(
                    chunks,
                    gaps,
                    overlaps,
                    requested_end_us=requested_end_us,
                    sample_count=sample_count,
                )
                if state == "complete" and _one_slice_start(segments) < 0:
                    reason = "in_pieces"
                outcomes.add((state, reason))

    assert outcomes == {
        ("complete", None),
        ("complete", "in_pieces"),
        ("partial", "window_crosses_gap"),
        ("partial", "window_crosses_overlap"),
        ("missing", "window_before_capture"),
        ("missing", "window_after_capture"),
    }
