from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_support.history_db_lifecycle import run_samples
from test_support.power import FakePiSysfs

from tests.recording.test_metrics_log_helpers import _started_snapshot_with_sample
from vibesensor.clock.boot import current_boot_id
from vibesensor.common.time_utils import parse_iso8601
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.domain.car import CarSnapshot
from vibesensor.history.history_db import HistoryDB
from vibesensor.power.monitor import PowerMonitor
from vibesensor.recording import finalize_stages
from vibesensor.recording._recorder_types import _build_run_metadata_record
from vibesensor.recording.run_schema import RunStartClock


def test_run_metadata_captures_active_car_snapshot(make_logger) -> None:
    settings_reader = type(
        "SettingsReaderStub",
        (),
        {
            "active_car_snapshot": lambda self: CarSnapshot(
                car_id="car-1",
                name="Primary",
                car_type="sedan",
                aspects={
                    "tire_width_mm": 255.0,
                    "tire_aspect_pct": 40.0,
                    "rim_in": 19.0,
                    "final_drive_ratio": 3.15,
                    "current_gear_ratio": 0.81,
                },
            ),
            "analysis_settings_snapshot": lambda self: AnalysisSettingsSnapshot(
                tire_width_mm=255.0,
                tire_aspect_pct=40.0,
                rim_in=19.0,
                final_drive_ratio=3.15,
                current_gear_ratio=0.81,
            ),
        },
    )()
    logger = make_logger(settings_reader=settings_reader)

    metadata = _build_run_metadata_record(logger, "run-1", "2026-01-01T00:00:00Z")

    assert metadata.incomplete_for_order_analysis is False
    assert metadata.car is not None
    assert metadata.car.car_id == "car-1"
    assert metadata.car.name == "Primary"
    assert metadata.car.car_type == "sedan"


@pytest.mark.parametrize(
    ("time_zone", "start_time_utc", "expected_offset_s"),
    [
        pytest.param("Europe/Amsterdam", "2026-10-04T08:52:51Z", 7200, id="cest-summer"),
        pytest.param("Europe/Amsterdam", "2026-01-15T08:00:00Z", 3600, id="cet-winter"),
        pytest.param(None, "2026-10-04T08:52:51Z", None, id="unknown-zone-is-utc"),
    ],
)
def test_run_metadata_records_the_users_time_zone_offset_not_the_servers(
    make_logger,
    time_zone: str | None,
    start_time_utc: str,
    expected_offset_s: int | None,
) -> None:
    """The Pi image runs Europe/London; a Dutch user's run must carry +02:00 in summer."""
    logger = make_logger(
        ui_preferences=SimpleNamespace(language="en", time_zone=time_zone),
    )

    metadata = _build_run_metadata_record(logger, "run-1", start_time_utc)

    assert metadata.recorded_utc_offset_seconds == expected_offset_s


def test_db_persists_when_jsonl_disabled(make_logger, tmp_path: Path) -> None:
    history_db = HistoryDB(tmp_path / "history.db")
    logger = make_logger(history_db=history_db, persist_history_db=True)

    snapshot = _started_snapshot_with_sample(logger)
    run_id = snapshot.run_id
    logger.stop_recording()

    assert history_db.get_run(run_id) is not None
    assert run_samples(history_db, run_id)


def test_a_run_started_before_the_pi_clock_was_set_is_marked_unverified(
    make_logger, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No RTC, no NTP, no browser yet: the run's wall times are wrong and say so.

    It also keeps its start on the monotonic clock, and its end stays on the same
    wrong clock base when NTP steps the clock mid-run, so a later correction can
    shift both and the duration stays the monotonic one.
    """
    history_db = HistoryDB(tmp_path / "history.db")
    clock = {"trusted": False}
    logger = make_logger(history_db=history_db, clock_trusted=lambda: clock["trusted"])

    started = _started_snapshot_with_sample(logger)
    # NTP sets the clock three days forward mid-run.
    stepped_now = (parse_iso8601(started.start_time_utc) + timedelta(days=3)).isoformat()
    monkeypatch.setattr(finalize_stages, "utc_now_iso", lambda: stepped_now)
    clock["trusted"] = True
    logger.stop_recording()
    verified = _started_snapshot_with_sample(logger).run_id
    logger.stop_recording()

    def stored(run_id: str) -> tuple[bool, bool, RunStartClock | None]:
        run = history_db.get_run(run_id)
        assert run is not None
        entry = next(entry for entry in history_db.list_runs() if entry.run_id == run_id)
        return (
            run.metadata.start_time_unverified,
            entry.start_time_unverified,
            (run.metadata.start_clock),
        )

    boot_id = current_boot_id()
    assert stored(started.run_id) == (
        True,
        True,
        RunStartClock(boot_id=boot_id, monotonic_s=started.start_mono_s) if boot_id else None,
    )
    assert stored(verified) == (False, False, None)
    unverified_run = history_db.get_run(started.run_id)
    verified_run = history_db.get_run(verified)
    assert unverified_run is not None and verified_run is not None
    duration = parse_iso8601(unverified_run.end_time_utc) - parse_iso8601(
        unverified_run.start_time_utc
    )
    assert timedelta(0) <= duration < timedelta(seconds=30)
    assert verified_run.end_time_utc == stepped_now


def test_a_run_during_which_the_supply_dipped_stores_it_and_the_next_run_does_not(
    make_logger, tmp_path: Path
) -> None:
    sysfs = FakePiSysfs(tmp_path / "sys")
    monitor = PowerMonitor(hwmon_dir=sysfs.hwmon, thermal_path=sysfs.thermal)
    history_db = HistoryDB(tmp_path / "history.db")
    logger = make_logger(history_db=history_db, power_issues_since=monitor.issues_since)

    dipped = _started_snapshot_with_sample(logger).run_id
    sysfs.set(undervoltage=True, celsius=82.0)
    monitor.poll()
    sysfs.set(undervoltage=False, celsius=50.0)
    monitor.poll()
    logger.stop_recording()
    clean = _started_snapshot_with_sample(logger).run_id
    monitor.poll()
    logger.stop_recording()

    def stored(run_id: str) -> tuple[str, ...]:
        run = history_db.get_run(run_id)
        assert run is not None
        return run.metadata.power_issues

    assert stored(dipped) == ("undervoltage", "overheated")
    assert stored(clean) == ()
