from __future__ import annotations

import pytest

from vibesensor.domain import CarSnapshot
from vibesensor.use_cases.run._recorder_types import _build_run_metadata_record


def test_recording_keeps_run_start_context_when_settings_change_mid_run(
    make_logger,
    mutable_fake_settings,
    fake_gps_monitor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    logger = make_logger(settings_reader=mutable_fake_settings, gps_monitor=fake_gps_monitor)
    logger.start_recording()
    snapshot = logger._session_snapshot()
    assert snapshot is not None

    initial_rows = logger._sample_flush.build_sample_records(
        run_id=snapshot.run_id,
        t_s=1.0,
        timestamp_utc="2026-02-16T12:00:00+00:00",
    )

    assert len(initial_rows) == 1
    initial_row = initial_rows[0]
    assert initial_row.final_drive_ratio == pytest.approx(3.08)
    assert initial_row.gear == pytest.approx(0.64)
    assert initial_row.engine_rpm is not None

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

    later_rows = logger._sample_flush.build_sample_records(
        run_id=snapshot.run_id,
        t_s=2.0,
        timestamp_utc="2026-02-16T12:00:01+00:00",
    )

    assert len(later_rows) == 1
    later_row = later_rows[0]
    assert later_row.final_drive_ratio == pytest.approx(initial_row.final_drive_ratio)
    assert later_row.gear == pytest.approx(initial_row.gear)
    assert later_row.engine_rpm == pytest.approx(initial_row.engine_rpm)

    metadata = _build_run_metadata_record(logger, snapshot.run_id, snapshot.start_time_utc)
    assert not hasattr(metadata, "tire_width_mm")
    assert metadata.analysis_settings.tire_width_mm == pytest.approx(285.0)
    assert metadata.car is not None
    assert metadata.car.car_id == "car-1"
    assert metadata.car.name == "Primary"
