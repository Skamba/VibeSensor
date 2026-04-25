from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
from vibesensor.use_cases.run._recorder_types import _build_run_metadata_record


def test_run_sensor_rows_stay_stable_when_live_metadata_changes(
    make_logger,
    fake_registry,
) -> None:
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
    )
    logger.start_recording()
    snapshot = logger._session_snapshot()
    assert snapshot is not None

    initial_rows = logger._sample_flush.build_sample_records(
        run_id=snapshot.run_id,
        t_s=1.0,
        timestamp_utc="2026-02-16T12:00:00+00:00",
    )
    assert len(initial_rows) == 1
    assert initial_rows[0].client_name == "Configured front left"
    assert initial_rows[0].location == "front_left_wheel"

    fake_registry._records[sensor_id].name = "Renamed live sensor"
    fake_registry._records[sensor_id].location_code = "rear_right_wheel"
    sensors_by_mac["aabbccddee01"] = {
        "name": "Configured rear right",
        "location_code": "rear_right_wheel",
    }

    later_rows = logger._sample_flush.build_sample_records(
        run_id=snapshot.run_id,
        t_s=2.0,
        timestamp_utc="2026-02-16T12:00:01+00:00",
    )
    assert len(later_rows) == 1
    assert later_rows[0].client_name == initial_rows[0].client_name
    assert later_rows[0].location == initial_rows[0].location

    metadata = _build_run_metadata_record(logger, snapshot.run_id, snapshot.start_time_utc)
    assert len(metadata.sensor_snapshots) == 1
    sensor_snapshot = metadata.sensor_snapshots[0]
    assert sensor_snapshot.sensor_id == sensor_id
    assert sensor_snapshot.display_name == "Configured front left"
    assert sensor_snapshot.location_code == "front_left_wheel"
    assert sensor_snapshot.mount_orientation == "radial"


def test_first_seen_sensor_gets_stable_snapshot_entry_during_run(
    make_logger,
    fake_registry,
    tmp_path: Path,
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
    logger.schedule_post_analysis = lambda _run_id: None
    logger.start_recording()
    snapshot = logger._session_snapshot()
    assert snapshot is not None

    logger._sample_flush.append_records(
        snapshot.run_id,
        snapshot.start_time_utc,
        snapshot.start_mono_s,
    )

    late_record = replace(
        fake_registry._records[active_sensor_id],
        client_id=late_sensor_id,
        name="Late joiner live",
        location_code="rear_left_wheel",
        firmware_version="2.0.0",
    )
    fake_registry._records[late_sensor_id] = late_record
    active_ids.append(late_sensor_id)
    sensors_by_mac["aabbccddee02"] = {
        "name": "Configured rear left",
        "location_code": "rear_left_wheel",
        "mount_orientation": "axial",
    }

    logger._sample_flush.append_records(
        snapshot.run_id,
        snapshot.start_time_utc,
        snapshot.start_mono_s,
    )

    sensors_by_mac["aabbccddee02"] = {
        "name": "Configured moved later",
        "location_code": "front_right_wheel",
        "mount_orientation": "rearward",
    }
    fake_registry._records[late_sensor_id].name = "Late joiner renamed live"
    fake_registry._records[late_sensor_id].location_code = "front_right_wheel"

    logger._sample_flush.append_records(
        snapshot.run_id,
        snapshot.start_time_utc,
        snapshot.start_mono_s,
    )
    logger.stop_recording()

    stored_metadata = history_db.run_repository.get_run(snapshot.run_id).metadata
    late_snapshot = stored_metadata.sensor_snapshot_for(late_sensor_id)
    assert late_snapshot is not None
    assert late_snapshot.display_name == "Configured rear left"
    assert late_snapshot.location_code == "rear_left_wheel"
    assert late_snapshot.mount_orientation == "axial"

    stored_samples = history_db.run_repository.get_run_samples(snapshot.run_id)
    late_rows = [sample for sample in stored_samples if sample.client_id == late_sensor_id]
    assert late_rows
    assert {sample.client_name for sample in late_rows} == {"Configured rear left"}
    assert {sample.location for sample in late_rows} == {"rear_left_wheel"}
