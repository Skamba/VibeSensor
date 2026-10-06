"""Re-date a stored run whose start was stamped on an unset wall clock.

The recorder stamps such a run's start with the wrong wall clock, its end with
start plus monotonic elapsed time (so both share one wrong clock base), and
stores where it started on ``time.monotonic`` with the boot id. Once the wall
clock is right, and still in that boot, the true start is ``wall_now -
(monotonic_now - start_monotonic)``. Start, end and every copy of them in the
metadata and analysis move by the same delta; the duration does not change.

The row's ``created_at`` was stamped on the same wrong clock as the start, so it
moves too (History lists runs by it). Its analysis times move only when they lie
before the true start: they were stamped before the clock was set, and left
there, the run would read as finished before it started. The delta is kept
as ``start_time_corrected_by_s``; exports re-time the sample rows from it. The
fallback UTC offset is recomputed for the true start in the browser's zone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import msgspec

from vibesensor.common.json_types import is_json_object
from vibesensor.common.json_utils import safe_json_dumps, safe_json_loads
from vibesensor.common.time_utils import parse_iso8601, utc_offset_seconds_in
from vibesensor.recording.run_metadata import run_metadata_from_json, run_metadata_to_json_object
from vibesensor.recording.run_schema import RunMetadata

__all__ = ["CorrectedRunTimes", "StoredRunTimes", "correct_run_times"]

_ANALYSIS_TIME_KEYS = ("start_time_utc", "end_time_utc", "report_date")


@dataclass(frozen=True, slots=True)
class StoredRunTimes:
    """The columns of one ``runs`` row that carry its wall-clock times."""

    run_id: str
    start_time_utc: str
    end_time_utc: str | None
    created_at: str
    analysis_started_at: str | None
    analysis_completed_at: str | None
    metadata_json: str
    analysis_json: str | None


@dataclass(frozen=True, slots=True)
class CorrectedRunTimes:
    start_time_utc: str
    end_time_utc: str | None
    created_at: str
    analysis_started_at: str | None
    analysis_completed_at: str | None
    metadata_json: str
    analysis_json: str | None


def correct_run_times(
    run: StoredRunTimes,
    *,
    boot_id: str,
    wall_now_s: float,
    monotonic_now_s: float,
    time_zone: str | None,
) -> CorrectedRunTimes | None:
    """Return *run* re-dated on the now-correct wall clock, or ``None`` if it cannot be.

    It cannot be when it carries no start clock (started on a trusted clock, or
    before start clocks were stored), started in another boot, or its metadata
    does not decode.
    """
    try:
        metadata = run_metadata_from_json(run.metadata_json)
    except (msgspec.DecodeError, TypeError, ValueError):
        return None
    start_clock = metadata.start_clock
    old_start = parse_iso8601(run.start_time_utc)
    if (
        start_clock is None
        or start_clock.boot_id != boot_id
        or start_clock.monotonic_s > monotonic_now_s
        or old_start is None
    ):
        return None
    new_start = datetime.fromtimestamp(
        wall_now_s - (monotonic_now_s - start_clock.monotonic_s),
        UTC,
    )
    delta = new_start - old_start
    old_end = parse_iso8601(run.end_time_utc)
    new_start_utc = new_start.isoformat()
    new_end_utc = (old_end + delta).isoformat() if old_end is not None else None
    redated = {run.start_time_utc: new_start_utc}
    if run.end_time_utc is not None and new_end_utc is not None:
        redated[run.end_time_utc] = new_end_utc

    metadata.start_time_utc = new_start_utc
    metadata.end_time_utc = new_end_utc
    if metadata.report_date is not None:
        metadata.report_date = redated.get(metadata.report_date, metadata.report_date)
    metadata.start_time_unverified = False
    metadata.start_clock = None
    metadata.start_time_corrected_by_s = round(delta.total_seconds(), 3)
    utc_offset = utc_offset_seconds_in(time_zone, new_start_utc)
    if utc_offset is not None:
        metadata.recorded_utc_offset_seconds = utc_offset
    created_at = parse_iso8601(run.created_at)
    return CorrectedRunTimes(
        start_time_utc=new_start_utc,
        end_time_utc=new_end_utc,
        created_at=(created_at + delta).isoformat() if created_at is not None else run.created_at,
        analysis_started_at=_moved_if_before(run.analysis_started_at, new_start, delta),
        analysis_completed_at=_moved_if_before(run.analysis_completed_at, new_start, delta),
        metadata_json=safe_json_dumps(run_metadata_to_json_object(metadata)),
        analysis_json=_redated_analysis_json(run, redated, metadata),
    )


def _moved_if_before(value: str | None, true_start: datetime, delta: timedelta) -> str | None:
    """Move a time stamped before the clock was set (it predates the true start)."""
    stamped = parse_iso8601(value)
    if stamped is None or stamped >= true_start:
        return value
    return (stamped + delta).isoformat()


def _redated_analysis_json(
    run: StoredRunTimes, redated: dict[str, str], corrected: RunMetadata
) -> str | None:
    """Replace the run's old times in the stored analysis and its metadata copy."""
    analysis = safe_json_loads(run.analysis_json, context=f"analysis of run {run.run_id}")
    if not is_json_object(analysis):
        return run.analysis_json
    sections = [analysis]
    if is_json_object(metadata := analysis.get("metadata")):
        metadata.pop("start_time_unverified", None)
        metadata.pop("start_clock", None)
        metadata["start_time_corrected_by_s"] = corrected.start_time_corrected_by_s
        if corrected.recorded_utc_offset_seconds is not None:
            metadata["recorded_utc_offset_seconds"] = corrected.recorded_utc_offset_seconds
        sections.append(metadata)
    for section in sections:
        for key in _ANALYSIS_TIME_KEYS:
            value = section.get(key)
            if isinstance(value, str) and value in redated:
                section[key] = redated[value]
    return safe_json_dumps(analysis)
