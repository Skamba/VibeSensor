from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
from vibesensor.domain import CarSnapshot
from vibesensor.use_cases.run import _recorder_runtime


class _StopLoop(Exception):
    pass


def test_recording_keeps_run_start_context_when_settings_change_mid_run(
    make_logger,
    mutable_fake_settings,
    fake_gps_monitor,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_db = create_history_persistence_adapters(tmp_path / "history.db")
    active_car_holder = [
        CarSnapshot(
            car_id="car-1",
            name="Primary",
            car_type="sedan",
            aspects={
                "tire_width_mm": 285.0,
                "tire_aspect_pct": 30.0,
                "rim_in": 21.0,
                "final_drive_ratio": 3.08,
                "current_gear_ratio": 0.64,
            },
        )
    ]
    monkeypatch.setattr(
        mutable_fake_settings,
        "active_car_snapshot",
        lambda: active_car_holder[0],
    )
    fake_gps_monitor.override_speed_mps = 10.0

    logger = make_logger(
        settings_reader=mutable_fake_settings,
        gps_monitor=fake_gps_monitor,
        history_db=history_db.run_repository,
    )
    status = logger.start_recording()
    run_id = status.run_id
    assert run_id is not None
    active_record = logger.registry.get("active")
    assert active_record is not None
    active_record.frames_total = 1

    sleep_calls = 0

    async def fake_sleep(_seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls == 1:
            mutable_fake_settings.values.update(
                {
                    "tire_width_mm": 315.0,
                    "tire_aspect_pct": 35.0,
                    "rim_in": 20.0,
                    "final_drive_ratio": 4.1,
                    "current_gear_ratio": 0.95,
                }
            )
            active_car_holder[0] = CarSnapshot(
                car_id="car-2",
                name="Changed",
                car_type="hatchback",
                aspects={
                    "tire_width_mm": 315.0,
                    "tire_aspect_pct": 35.0,
                    "rim_in": 20.0,
                    "final_drive_ratio": 4.1,
                    "current_gear_ratio": 0.95,
                },
            )
            active_record.frames_total = 2
            return
        raise _StopLoop

    monkeypatch.setattr(_recorder_runtime.asyncio, "sleep", fake_sleep)

    with pytest.raises(_StopLoop):
        asyncio.run(logger.run())

    logger.stop_recording()
    assert logger.wait_for_post_analysis(timeout_s=3.0)

    stored_run = history_db.run_repository.get_run(run_id)
    assert stored_run is not None
    metadata = stored_run.metadata
    assert metadata.analysis_settings.tire_width_mm == pytest.approx(285.0)
    assert metadata.car is not None
    assert metadata.car.car_id == "car-1"
    assert metadata.car.name == "Primary"

    stored_samples = history_db.run_repository.get_run_samples(run_id)
    assert len(stored_samples) == 2
    reference_rpm = stored_samples[0].engine_rpm
    assert reference_rpm is not None
    for sample in stored_samples:
        assert sample.final_drive_ratio == pytest.approx(3.08)
        assert sample.gear == pytest.approx(0.64)
        assert sample.engine_rpm == pytest.approx(reference_rpm)
