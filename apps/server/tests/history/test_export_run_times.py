"""Exports time a run's sample rows on the run's own clock, and stamp entries in the user's zone.

A run started before the Pi clock was set stamped its rows with that wrong
clock. Once corrected, its start moves but the rows do not: the export re-times
them as start plus ``t_s``, so they match the corrected start and end, also when
NTP stepped the clock mid-run.
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from test_support.history_db_lifecycle import create_recording_run
from test_support.report_helpers import report_sample

from vibesensor.clock.run_times import RunTimeCorrector
from vibesensor.common.time_utils import parse_iso8601
from vibesensor.history.exports import HistoryExportService
from vibesensor.history.history_db import HistoryDB
from vibesensor.recording.run_schema import RunStartClock
from vibesensor.recording.sensor_frame_mapping import sensor_frames_from_mappings
from vibesensor.web.history_services import ProjectedHistoryExportService

_BOOT = "boot-a"
_WRONG_START = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
_TRUE_START = datetime(2026, 6, 1, 11, 50, tzinfo=UTC)
_START_MONO_S = 1000.0
_ROW_T_S = (0.5, 1.5, 2.5, 3.5)
_ZONE = "Europe/Amsterdam"


def _record(db: HistoryDB, run_id: str, start_clock: RunStartClock | None) -> None:
    """Four rows at ``t_s`` 0.5..3.5; NTP stepped the clock to the true time after two."""
    metadata = create_recording_run(db, run_id, started_at=_WRONG_START.isoformat())
    end = (_WRONG_START + timedelta(seconds=4)).isoformat()
    metadata = replace(
        metadata,
        start_time_utc=_WRONG_START.isoformat(),
        end_time_utc=end,
        start_time_unverified=start_clock is not None,
        start_clock=start_clock,
    )
    db.update_run_metadata(run_id, metadata)
    rows = []
    for index, t_s in enumerate(_ROW_T_S):
        base = _WRONG_START if index < 2 else _TRUE_START
        row = report_sample(index, speed_kmh=60.0, dominant_freq_hz=15.0, peak_amp_g=0.1)
        row.update(
            run_id=run_id,
            t_s=t_s,
            timestamp_utc=(base + timedelta(seconds=t_s)).isoformat(),
        )
        rows.append(row)
    db.append_samples(run_id, sensor_frames_from_mappings(rows))
    db.finalize_run(run_id, end, metadata)
    db.store_analysis_error(run_id, "not analysed in this test")


async def _export(db: HistoryDB, run_id: str) -> tuple[list[datetime | None], list[tuple]]:
    service = ProjectedHistoryExportService(HistoryExportService(db), time_zone=lambda: _ZONE)
    export = await service.build_export(run_id)
    with zipfile.ZipFile(io.BytesIO(b"".join(export.iter_bytes()))) as archive:
        csv_text = archive.read(f"{run_id}_analysis_windows.csv").decode("utf-8")
        entry_times = [info.date_time for info in archive.infolist()]
    rows = csv.DictReader(io.StringIO(csv_text))
    return [parse_iso8601(row["timestamp_utc"]) for row in rows], entry_times


@pytest.mark.asyncio
async def test_corrected_runs_export_their_rows_on_the_corrected_clock(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    _record(db, "corrected", RunStartClock(boot_id=_BOOT, monotonic_s=_START_MONO_S))
    _record(db, "trusted", None)
    now_mono_s = _START_MONO_S + 600.0
    corrector = RunTimeCorrector(
        history_db=db,
        clock_trusted=lambda: True,
        time_zone=lambda: _ZONE,
        boot_id=lambda: _BOOT,
        now=(_TRUE_START + timedelta(seconds=600)).timestamp,
        monotonic=lambda: now_mono_s,
    )
    assert corrector.correct() == ["corrected"]

    before = datetime.now(ZoneInfo(_ZONE)).replace(tzinfo=None, microsecond=0)
    corrected_rows, entry_times = await _export(db, "corrected")
    after = datetime.now(ZoneInfo(_ZONE)).replace(tzinfo=None)
    assert corrected_rows == [_TRUE_START + timedelta(seconds=t_s) for t_s in _ROW_T_S]
    # A run started on a trusted clock keeps the times its rows were stamped with.
    trusted_rows, _ = await _export(db, "trusted")
    assert trusted_rows == [
        (_WRONG_START if index < 2 else _TRUE_START) + timedelta(seconds=t_s)
        for index, t_s in enumerate(_ROW_T_S)
    ]
    # ZIP entry times have no zone: the export time in the user's zone, not the Pi's.
    assert entry_times
    for entry_time in entry_times:
        assert before - timedelta(seconds=2) <= datetime(*entry_time) <= after
    db.close()
