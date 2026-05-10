from __future__ import annotations

from vibesensor.shared.types.raw_capture import RawCaptureLossStats


def test_recording_session_start_owns_context_snapshots_and_ingest_drop_baseline(
    make_logger,
) -> None:
    recorder = make_logger()
    active = recorder.registry.get("active")
    assert active is not None
    active.server_queue_drops = 2

    snapshot = recorder._recording_session.start_new_run()
    active.server_queue_drops = 5

    assert recorder.processor.flush_calls == [("active", "recording run start")]
    assert recorder._lifecycle.run_id == snapshot.run_id
    assert recorder._recording_session.run_context_snapshot(snapshot.run_id).analysis_settings
    assert recorder._recording_session.run_sensor_snapshots_for_run(snapshot.run_id)
    assert recorder._recording_session.ingest_drop_losses() == {
        "active": RawCaptureLossStats(udp_ingest_queue_drop_count=3),
    }


def test_recording_session_clear_stopped_run_drops_active_context(make_logger) -> None:
    recorder = make_logger()
    snapshot = recorder._recording_session.start_new_run()
    assert recorder._recording_session.run_sensor_snapshots_for_run(snapshot.run_id)

    recorder._recording_session.clear_stopped_run()

    assert recorder._recording_session.run_sensor_snapshots_for_run(snapshot.run_id) == ()
    assert recorder._recording_session.ingest_drop_losses() is None
