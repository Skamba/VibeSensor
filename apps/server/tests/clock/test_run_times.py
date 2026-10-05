"""Runs recorded before the Pi clock was set get their true times once it is set.

Drives real history storage and the real post-analysis worker: the corrector
runs after each analysis and when the clock becomes trusted, like in the app.
"""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_support.history_db_lifecycle import create_recording_run
from test_support.report_helpers import report_sample

from vibesensor.analysis.post_analysis import PostAnalysisWorker
from vibesensor.clock.run_times import RunTimeCorrector
from vibesensor.common.time_utils import parse_iso8601
from vibesensor.domain.run_status import RunStatus
from vibesensor.history.history_db import HistoryDB
from vibesensor.recording.run_schema import RunStartClock
from vibesensor.recording.sensor_frame_mapping import sensor_frames_from_mappings

_BOOT = "boot-a"
# The Pi booted without network and restored a clock months behind (winter time).
_WRONG_START = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
_RUN_S = 300.0
# The clock is set at 12:00 real time (summer time; before the test's real now, which
# stamps analyses run after the clock was set), 600 s after the runs started on the
# monotonic clock.
_TRUE_NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
_START_MONO_S = 1000.0
_NOW_MONO_S = _START_MONO_S + 600.0
_TRUE_START = _TRUE_NOW - timedelta(seconds=_NOW_MONO_S - _START_MONO_S)
_ZONE = "Europe/Amsterdam"
_WINTER_OFFSET_S = 3600
_SUMMER_OFFSET_S = 7200


def _record(db: HistoryDB, run_id: str, start_clock: RunStartClock | None) -> None:
    metadata = create_recording_run(db, run_id, started_at=_WRONG_START.isoformat())
    end = (_WRONG_START + timedelta(seconds=_RUN_S)).isoformat()
    metadata = replace(
        metadata,
        start_time_utc=_WRONG_START.isoformat(),
        end_time_utc=end,
        start_time_unverified=start_clock is not None,
        start_clock=start_clock,
        # Taken from the browser zone at the wrong start: winter time.
        recorded_utc_offset_seconds=_WINTER_OFFSET_S,
    )
    db.update_run_metadata(run_id, metadata)
    db.append_samples(
        run_id,
        sensor_frames_from_mappings(
            [
                report_sample(index, speed_kmh=60.0 + index, dominant_freq_hz=15.0, peak_amp_g=0.12)
                for index in range(8)
            ]
        ),
    )
    db.finalize_run(run_id, end, metadata)


def _stamp_on_the_wrong_clock(db_path: Path, run_id: str) -> None:
    """Stamp the row's own times as the unset Pi clock did (tests run on a set clock)."""
    stamps = {
        "created_at": _WRONG_START + timedelta(seconds=1),
        "analysis_started_at": _WRONG_START + timedelta(seconds=_RUN_S + 1),
        "analysis_completed_at": _WRONG_START + timedelta(seconds=_RUN_S + 2),
    }
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE runs SET created_at = ?, analysis_started_at = ?, analysis_completed_at = ? "
            "WHERE run_id = ?",
            (*(stamp.isoformat() for stamp in stamps.values()), run_id),
        )
    conn.close()


def _row_times(db: HistoryDB, run_id: str) -> tuple[datetime | None, ...]:
    run = db.get_run(run_id)
    assert run is not None
    return (
        parse_iso8601(run.created_at),
        parse_iso8601(run.analysis_started_at),
        parse_iso8601(run.analysis_completed_at),
    )


def _times(db: HistoryDB, run_id: str) -> dict[str, object]:
    run = db.get_run(run_id)
    assert run is not None and run.analysis is not None
    analysis = run.analysis.to_json_object()
    analysis_metadata = analysis["metadata"]
    assert isinstance(analysis_metadata, dict)
    entry = next(entry for entry in db.list_runs() if entry.run_id == run_id)
    return {
        "status": run.status,
        "start": parse_iso8601(run.start_time_utc),
        "end": parse_iso8601(run.end_time_utc),
        "metadata": (
            parse_iso8601(run.metadata.start_time_utc),
            parse_iso8601(run.metadata.end_time_utc),
            run.metadata.start_time_unverified,
            run.metadata.start_clock,
            run.metadata.start_time_corrected_by_s,
            run.metadata.recorded_utc_offset_seconds,
        ),
        "analysis": (
            parse_iso8601(analysis["start_time_utc"]),
            parse_iso8601(analysis["end_time_utc"]),
            parse_iso8601(analysis["report_date"]),
        ),
        "analysis_metadata": (
            parse_iso8601(analysis_metadata["start_time_utc"]),
            parse_iso8601(analysis_metadata["end_time_utc"]),
            analysis_metadata.get("start_time_unverified", False),
            "start_clock" in analysis_metadata,
            analysis_metadata.get("start_time_corrected_by_s"),
            analysis_metadata.get("recorded_utc_offset_seconds"),
        ),
        "listed_unverified": entry.start_time_unverified,
    }


def _expected(
    start: datetime,
    *,
    unverified: bool,
    start_clock: RunStartClock | None,
    corrected_by_s: float | None = None,
    utc_offset_s: int = _WINTER_OFFSET_S,
):
    end = start + timedelta(seconds=_RUN_S)
    return {
        "status": RunStatus.COMPLETE,
        "start": start,
        "end": end,
        "metadata": (start, end, unverified, start_clock, corrected_by_s, utc_offset_s),
        "analysis": (start, end, end),
        "analysis_metadata": (
            start,
            end,
            unverified,
            start_clock is not None,
            corrected_by_s,
            utc_offset_s,
        ),
        "listed_unverified": unverified,
    }


def _corrector(db: HistoryDB, trusted: dict[str, bool]) -> RunTimeCorrector:
    return RunTimeCorrector(
        history_db=db,
        clock_trusted=lambda: trusted["now"],
        time_zone=lambda: _ZONE,
        boot_id=lambda: _BOOT,
        now=_TRUE_NOW.timestamp,
        monotonic=lambda: _NOW_MONO_S,
    )


def test_this_boots_unverified_runs_are_redated_once_the_clock_is_trusted(
    tmp_path: Path,
) -> None:
    db = HistoryDB(tmp_path / "history.db")
    trusted = {"now": False}
    corrector = _corrector(db, trusted)
    worker = PostAnalysisWorker(history_db=db, after_run=corrector.correct)
    this_boot = RunStartClock(boot_id=_BOOT, monotonic_s=_START_MONO_S)
    earlier_boot = RunStartClock(boot_id="boot-z", monotonic_s=_START_MONO_S)
    for run_id, start_clock in (
        ("analysed-before-the-clock-was-set", this_boot),
        ("analysing-when-the-clock-was-set", this_boot),
        ("earlier-boot", earlier_boot),
        ("trusted", None),
    ):
        _record(db, run_id, start_clock)
    for run_id in ("analysed-before-the-clock-was-set", "earlier-boot", "trusted"):
        worker.schedule(run_id)
    assert worker.wait(timeout_s=30.0)
    for run_id in ("analysed-before-the-clock-was-set", "analysing-when-the-clock-was-set"):
        _stamp_on_the_wrong_clock(tmp_path / "history.db", run_id)
    assert corrector.correct() == []

    trusted["now"] = True
    # A browser sets the clock: the analysing run is left until its analysis is stored.
    assert corrector.correct() == ["analysed-before-the-clock-was-set"]
    worker.schedule("analysing-when-the-clock-was-set")
    assert worker.wait(timeout_s=30.0)

    delta = _TRUE_START - _WRONG_START
    for run_id in ("analysed-before-the-clock-was-set", "analysing-when-the-clock-was-set"):
        # The offset is recomputed for the true (summer) start in the browser's zone.
        assert _times(db, run_id) == _expected(
            _TRUE_START,
            unverified=False,
            start_clock=None,
            corrected_by_s=delta.total_seconds(),
            utc_offset_s=_SUMMER_OFFSET_S,
        )
    # History sorts by created_at and retention prunes by analysis_completed_at:
    # both move off the wrong clock, so the run is not listed or pruned as months old.
    assert _row_times(db, "analysed-before-the-clock-was-set") == (
        _TRUE_START + timedelta(seconds=1),
        _TRUE_START + timedelta(seconds=_RUN_S + 1),
        _TRUE_START + timedelta(seconds=_RUN_S + 2),
    )
    # Queued before the clock was set, analysed after: only the start moves.
    created_at, analysis_started_at, analysis_completed_at = _row_times(
        db, "analysing-when-the-clock-was-set"
    )
    assert (created_at, analysis_started_at) == (
        _TRUE_START + timedelta(seconds=1),
        _TRUE_START + timedelta(seconds=_RUN_S + 1),
    )
    assert analysis_completed_at is not None
    assert _TRUE_NOW < analysis_completed_at <= datetime.now(UTC)
    # Another boot's monotonic clock says nothing about this one: still unverified.
    assert _times(db, "earlier-boot") == _expected(
        _WRONG_START, unverified=True, start_clock=earlier_boot
    )
    assert _times(db, "trusted") == _expected(_WRONG_START, unverified=False, start_clock=None)
    assert corrector.correct() == []
    db.close()


@pytest.mark.asyncio
async def test_runs_are_redated_when_ntp_sets_the_clock_with_no_browser_open(
    tmp_path: Path,
) -> None:
    db = HistoryDB(tmp_path / "history.db")
    trusted = {"now": False}
    corrector = _corrector(db, trusted)
    _record(db, "unverified", RunStartClock(boot_id=_BOOT, monotonic_s=_START_MONO_S))
    db.store_analysis_error("unverified", "analysis failed")
    watch = asyncio.create_task(corrector.watch(poll_s=0.01))
    try:
        await asyncio.sleep(0.05)
        assert db.get_run("unverified").metadata.start_time_unverified

        # No browser report, no analysis, no restart: only the kernel clock syncs.
        trusted["now"] = True
        for _ in range(200):
            await asyncio.sleep(0.01)
            if not db.get_run("unverified").metadata.start_time_unverified:
                break
        assert parse_iso8601(db.get_run("unverified").start_time_utc) == _TRUE_START
    finally:
        watch.cancel()
        db.close()
