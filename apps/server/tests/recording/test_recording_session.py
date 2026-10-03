from __future__ import annotations

from vibesensor.recording.raw_capture import RawCaptureLossStats
from vibesensor.recording.run_schema import RunGuidedPhase


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


def _clock(session):
    """Pin the run clock to exact floats so step times compare exactly."""
    now = [1000.0]
    session._live_start_mono_s = now[0]
    session._monotonic = lambda: now[0]
    return now


def test_guided_phases_close_each_step_when_the_next_starts(make_logger) -> None:
    recorder = make_logger()
    run_id = recorder.start_recording().run_id
    session = recorder._recording_session
    now = _clock(session)

    now[0] += 5.0
    session.mark_guided_phase("sweep")
    assert recorder.status().guided_phases_completed == ()
    now[0] += 20.0
    session.mark_guided_phase("hold")
    now[0] += 10.0
    session.mark_guided_phase("coast_down")
    assert session.current_guided_phase() == "coast_down"
    assert recorder.status().guided_phases_completed == ("sweep", "hold")
    now[0] += 8.0
    session.mark_guided_phase(None)

    assert session.current_guided_phase() is None
    assert session.guided_phases_for_run(run_id) == (
        RunGuidedPhase("sweep", 5.0, 25.0),
        RunGuidedPhase("hold", 25.0, 35.0),
        RunGuidedPhase("coast_down", 35.0, 43.0),
    )
    assert recorder.status().guided_phase is None
    # A reloaded Live page restores the finished guided test from the status.
    assert recorder.status().guided_phases_completed == ("sweep", "hold", "coast_down")


def test_repeated_guided_steps_are_listed_once(make_logger) -> None:
    recorder = make_logger()
    recorder.start_recording()

    for phase in ("sweep", "hold", "sweep", "hold", None):
        recorder.mark_guided_phase(phase)

    assert recorder.status().guided_phases_completed == ("sweep", "hold")


def test_guided_phase_is_ignored_without_an_active_recording(make_logger) -> None:
    recorder = make_logger()

    status = recorder.mark_guided_phase("sweep")

    assert status.guided_phase is None
    assert recorder._recording_session.current_guided_phase() is None


def test_guided_phases_reset_with_each_new_run(make_logger) -> None:
    recorder = make_logger()
    first = recorder.start_recording().run_id
    assert recorder.mark_guided_phase("hold").guided_phase == "hold"
    assert recorder.mark_guided_phase("coast_down").guided_phases_completed == ("hold",)
    recorder.stop_recording()
    second = recorder.start_recording().run_id

    session = recorder._recording_session
    assert session.guided_phases_for_run(first) == ()
    assert session.guided_phases_for_run(second) == ()
    assert recorder.status().guided_phase is None
    assert recorder.status().guided_phases_completed == ()
