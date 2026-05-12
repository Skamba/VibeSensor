from __future__ import annotations

from pathlib import Path

import pytest

from tests.use_cases.run.test_metrics_log_helpers import _started_snapshot_with_sample
from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
from vibesensor.domain import AnalysisSettingsSnapshot, CarSnapshot
from vibesensor.use_cases.run._recorder_types import _build_run_metadata_record


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


def test_run_metadata_captures_recorded_utc_offset(
    make_logger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = make_logger()
    monkeypatch.setattr(
        "vibesensor.use_cases.run._recorder_types.current_utc_offset_seconds",
        lambda: 7200,
    )

    metadata = _build_run_metadata_record(logger, "run-1", "2026-01-01T00:00:00Z")

    assert metadata.recorded_utc_offset_seconds == 7200


def test_db_persists_when_jsonl_disabled(make_logger, tmp_path: Path) -> None:
    history_db = create_history_persistence_adapters(tmp_path / "history.db")
    logger = make_logger(history_db=history_db.run_repository, persist_history_db=True)

    snapshot = _started_snapshot_with_sample(logger)
    run_id = snapshot.run_id
    logger.stop_recording()

    assert history_db.run_repository.get_run(run_id) is not None
    assert history_db.run_repository.get_run_samples(run_id)
