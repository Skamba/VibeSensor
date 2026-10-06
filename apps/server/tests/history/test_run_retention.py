"""Run history is kept until the disk runs low, then the oldest finished runs go.

The Pi is the owner's only store of past drives, so age alone never deletes a
run. At startup, while the disk holding the history has less free than the
safe minimum, the oldest finished run (in recording order) is deleted with its
raw capture.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_support.history_db_lifecycle import (
    create_analyzing_run,
    create_completed_run,
    create_error_run,
    create_recording_run,
)
from test_support.history_db_sql import execute_statements

from vibesensor.app import composition
from vibesensor.history.history_db import HistoryDB
from vibesensor.recording.sensor_frame_mapping import sensor_frame_from_mapping

_RAW_BYTES = 1_000_000
_DISK_FREE = 50_000_000


def _with_raw_capture(db_path: Path, run_id: str) -> None:
    run_dir = db_path.parent / "raw-runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "sensor-a.raw.i16le").write_bytes(b"\0" * _RAW_BYTES)


def _disk(db_path: Path) -> object:
    """A disk whose free space grows by the raw capture bytes deleted since now."""
    raw_root = db_path.parent / "raw-runs"

    def raw_bytes() -> int:
        return sum(path.stat().st_size for path in raw_root.rglob("*") if path.is_file())

    held = raw_bytes()
    return lambda: _DISK_FREE + held - raw_bytes()


def test_the_oldest_finished_runs_go_first_until_enough_is_free(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    db = HistoryDB(db_path)
    create_completed_run(db, "first")
    create_error_run(db, "second")
    create_analyzing_run(db, "being-analysed")
    create_completed_run(db, "newest")
    for run_id in ("first", "second", "being-analysed", "newest"):
        _with_raw_capture(db_path, run_id)
    # A run recorded while the clock was wrong carries a date in the future:
    # recording order, not its timestamps, decides which run is oldest.
    future = (datetime.now(UTC) + timedelta(days=400)).isoformat()
    execute_statements(
        db,
        (
            "UPDATE runs SET created_at = ?, analysis_completed_at = ? WHERE run_id = 'first'",
            (future, future),
        ),
    )

    deleted = db.prune_oldest_runs_for_free_space(
        _DISK_FREE + int(1.5 * _RAW_BYTES), disk_free_bytes=_disk(db_path)
    )

    assert deleted == ["first", "second"]
    assert [run.run_id for run in db.list_runs()] == ["newest", "being-analysed"]
    assert sorted(path.name for path in (tmp_path / "raw-runs").iterdir()) == [
        "being-analysed",
        "newest",
    ]
    db.close()


def test_space_a_deleted_run_leaves_in_the_database_counts_as_free(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    db = HistoryDB(db_path)
    create_recording_run(db, "long-drive")
    db.append_samples(
        "long-drive",
        [sensor_frame_from_mapping({"t_s": 0.25 * i, "client_id": "a"}) for i in range(4000)],
    )
    db.finalize_run("long-drive", "2026-01-01T00:20:00Z")
    db.store_analysis_error("long-drive", "failed")
    create_completed_run(db, "next-drive")

    # The database file does not shrink, but the pages the long drive's rows
    # held are free for the next runs: deleting it is enough.
    deleted = db.prune_oldest_runs_for_free_space(
        _DISK_FREE + 64 * 1024, disk_free_bytes=lambda: _DISK_FREE
    )

    assert deleted == ["long-drive"]
    assert db.get_run("next-drive") is not None
    db.close()


def test_runs_still_being_analysed_stay_however_low_the_disk_is(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    db = HistoryDB(db_path)
    create_completed_run(db, "done")
    create_analyzing_run(db, "being-analysed")

    deleted = db.prune_oldest_runs_for_free_space(
        _DISK_FREE * 10, disk_free_bytes=lambda: _DISK_FREE
    )

    assert deleted == ["done"]
    assert [run.run_id for run in db.list_runs()] == ["being-analysed"]
    db.close()


def _start(db_path: Path, monkeypatch: pytest.MonkeyPatch, *, free_bytes: int) -> HistoryDB:
    """Open the history the way the server's startup does, on a disk with *free_bytes* free."""
    usage = shutil.disk_usage(db_path.parent)
    monkeypatch.setattr(
        composition.shutil,
        "disk_usage",
        lambda _path: usage._replace(free=free_bytes),
    )
    config = SimpleNamespace(logging=SimpleNamespace(history_db_path=db_path))
    return composition.create_history_db(config, corruption_reporter=lambda _details: None)


def test_a_month_old_run_is_kept_at_startup_while_the_disk_has_room(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "history.db"
    db = HistoryDB(db_path)
    create_completed_run(db, "last-month")
    month_ago = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    execute_statements(
        db,
        (
            "UPDATE runs SET created_at = ?, end_time_utc = ?, analysis_completed_at = ? "
            "WHERE run_id = 'last-month'",
            (month_ago, month_ago, month_ago),
        ),
    )
    db.close()

    db = _start(db_path, monkeypatch, free_bytes=composition.RUN_HISTORY_MIN_FREE_BYTES)
    assert db.get_run("last-month") is not None
    db.close()

    db = _start(db_path, monkeypatch, free_bytes=composition.RUN_HISTORY_MIN_FREE_BYTES - 1)
    assert db.get_run("last-month") is None
    db.close()
