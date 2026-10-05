from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from test_support.history_db_lifecycle import run_samples

from tests.recording.test_metrics_log_helpers import _started_snapshot_with_sample
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.domain.car import CarSnapshot
from vibesensor.history.history_db import HistoryDB
from vibesensor.recording._recorder_types import _build_run_metadata_record


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
    make_logger, tmp_path: Path
) -> None:
    """No RTC, no NTP, no browser yet: the run's wall times are wrong and say so."""
    history_db = HistoryDB(tmp_path / "history.db")
    clock = {"trusted": False}
    logger = make_logger(history_db=history_db, clock_trusted=lambda: clock["trusted"])

    unverified = _started_snapshot_with_sample(logger).run_id
    # A browser sets the clock mid-run: the run started on the wrong time all the same.
    clock["trusted"] = True
    logger.stop_recording()
    verified = _started_snapshot_with_sample(logger).run_id
    logger.stop_recording()

    def flags(run_id: str) -> tuple[bool, bool]:
        run = history_db.get_run(run_id)
        assert run is not None
        entry = next(entry for entry in history_db.list_runs() if entry.run_id == run_id)
        return run.metadata.start_time_unverified, entry.start_time_unverified

    assert flags(unverified) == (True, True)
    assert flags(verified) == (False, False)
