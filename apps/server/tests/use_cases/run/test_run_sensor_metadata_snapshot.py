from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
from vibesensor.use_cases.run import _recorder_runtime


class _StopLoop(Exception):
    pass


def test_run_sensor_rows_stay_stable_when_live_metadata_changes(
    make_logger,
    fake_registry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_db = create_history_persistence_adapters(tmp_path / "history.db")
    sensor_id = "AA:BB:CC:DD:EE:01"
    active_ids = [sensor_id]
    fake_registry._records[sensor_id] = replace(
        fake_registry._records.pop("active"),
        client_id=sensor_id,
        name="Front-left live name",
        location_code="front_left_wheel",
    )
    fake_registry.active_client_ids = lambda: list(active_ids)
    sensors_by_mac = {
        "aabbccddee01": {
            "name": "Configured front left",
            "location_code": "front_left_wheel",
            "mount_orientation": "radial",
        }
    }
    sensor_metadata_reader = MagicMock()
    sensor_metadata_reader.get_sensors.side_effect = lambda: sensors_by_mac

    logger = make_logger(
        registry=fake_registry,
        sensor_metadata_reader=sensor_metadata_reader,
        history_db=history_db.run_repository,
    )
    status = logger.start_recording()
    run_id = status.run_id
    assert run_id is not None
    active_record = fake_registry.get(sensor_id)
    assert active_record is not None
    active_record.frames_total = 1

    sleep_calls = 0

    async def fake_sleep(_seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls == 1:
            active_record.frames_total = 2
            active_record.name = "Renamed live sensor"
            active_record.location_code = "rear_right_wheel"
            sensors_by_mac["aabbccddee01"] = {
                "name": "Configured rear right",
                "location_code": "rear_right_wheel",
            }
            return
        raise _StopLoop

    monkeypatch.setattr(_recorder_runtime.asyncio, "sleep", fake_sleep)

    with pytest.raises(_StopLoop):
        asyncio.run(logger.run())

    logger.stop_recording()
    assert logger.wait_for_post_analysis(timeout_s=3.0)

    stored_run = history_db.run_repository.get_run(run_id)
    assert stored_run is not None
    sensor_snapshot = stored_run.metadata.sensor_snapshot_for(sensor_id)
    assert sensor_snapshot is not None
    assert sensor_snapshot.display_name == "Configured front left"
    assert sensor_snapshot.location_code == "front_left_wheel"
    assert sensor_snapshot.mount_orientation == "radial"

    stored_samples = history_db.run_repository.get_run_samples(run_id)
    assert len(stored_samples) == 2
    assert {sample.client_name for sample in stored_samples} == {"Configured front left"}
    assert {sample.location for sample in stored_samples} == {"front_left_wheel"}


def test_first_seen_sensor_gets_stable_snapshot_entry_during_run(
    make_logger,
    fake_registry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_db = create_history_persistence_adapters(tmp_path / "history.db")
    active_sensor_id = "AA:BB:CC:DD:EE:01"
    late_sensor_id = "AA:BB:CC:DD:EE:02"
    active_ids = [active_sensor_id]
    fake_registry._records[active_sensor_id] = replace(
        fake_registry._records.pop("active"),
        client_id=active_sensor_id,
        name="Front-left live name",
        location_code="front_left_wheel",
    )
    sensors_by_mac = {
        "aabbccddee01": {
            "name": "Configured front left",
            "location_code": "front_left_wheel",
            "mount_orientation": "radial",
        }
    }
    sensor_metadata_reader = MagicMock()
    sensor_metadata_reader.get_sensors.side_effect = lambda: sensors_by_mac
    fake_registry.active_client_ids = lambda: list(active_ids)

    logger = make_logger(
        registry=fake_registry,
        sensor_metadata_reader=sensor_metadata_reader,
        history_db=history_db.run_repository,
    )
    status = logger.start_recording()
    run_id = status.run_id
    assert run_id is not None
    active_record = fake_registry.get(active_sensor_id)
    assert active_record is not None
    active_record.frames_total = 1

    late_record = replace(
        fake_registry._records[active_sensor_id],
        client_id=late_sensor_id,
        name="Late joiner live",
        location_code="rear_left_wheel",
        firmware_version="2.0.0",
        frames_total=0,
    )
    sleep_calls = 0

    async def fake_sleep(_seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls == 1:
            fake_registry._records[late_sensor_id] = late_record
            active_ids.append(late_sensor_id)
            sensors_by_mac["aabbccddee02"] = {
                "name": "Configured rear left",
                "location_code": "rear_left_wheel",
                "mount_orientation": "axial",
            }
            active_record.frames_total = 2
            late_record.frames_total = 1
            return
        if sleep_calls == 2:
            sensors_by_mac["aabbccddee02"] = {
                "name": "Configured moved later",
                "location_code": "front_right_wheel",
                "mount_orientation": "rearward",
            }
            fake_registry._records[late_sensor_id].name = "Late joiner renamed live"
            fake_registry._records[late_sensor_id].location_code = "front_right_wheel"
            active_record.frames_total = 3
            fake_registry._records[late_sensor_id].frames_total = 2
            return
        raise _StopLoop

    monkeypatch.setattr(_recorder_runtime.asyncio, "sleep", fake_sleep)

    with pytest.raises(_StopLoop):
        asyncio.run(logger.run())

    logger.stop_recording()
    assert logger.wait_for_post_analysis(timeout_s=3.0)

    stored_run = history_db.run_repository.get_run(run_id)
    assert stored_run is not None
    stored_metadata = stored_run.metadata
    late_snapshot = stored_metadata.sensor_snapshot_for(late_sensor_id)
    assert late_snapshot is not None
    assert late_snapshot.display_name == "Configured rear left"
    assert late_snapshot.location_code == "rear_left_wheel"
    assert late_snapshot.mount_orientation == "axial"

    stored_samples = history_db.run_repository.get_run_samples(run_id)
    late_rows = [sample for sample in stored_samples if sample.client_id == late_sensor_id]
    assert len(late_rows) == 2
    assert {sample.client_name for sample in late_rows} == {"Configured rear left"}
    assert {sample.location for sample in late_rows} == {"rear_left_wheel"}
