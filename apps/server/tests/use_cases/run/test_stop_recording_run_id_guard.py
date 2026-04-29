from __future__ import annotations


def test_stop_recording_skips_stale_run_id(make_logger) -> None:
    logger = make_logger()

    initial = logger.start_recording()
    assert initial.run_id is not None

    restarted = logger.start_recording()
    assert restarted.enabled is True
    assert restarted.run_id is not None
    assert restarted.run_id != initial.run_id

    guarded = logger.stop_recording(_only_if_run_id=initial.run_id, reason="no_data_timeout")

    assert guarded.enabled is True
    assert guarded.run_id == restarted.run_id
    assert logger.status().run_id == restarted.run_id


def test_stop_recording_stops_matching_run_id(make_logger) -> None:
    logger = make_logger()

    started = logger.start_recording()
    assert started.run_id is not None

    stopped = logger.stop_recording(_only_if_run_id=started.run_id, reason="no_data_timeout")

    assert stopped.enabled is False
    assert stopped.run_id is None
    assert logger.status().enabled is False
