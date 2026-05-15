from __future__ import annotations

import pytest

from vibesensor.use_cases.run.lifecycle_state import ActiveRunSnapshot


# Remaining private seam: these tests need a deterministic active recorder plus
# exactly one flush without running the async loop. Assertions stay on emitted
# samples, status, and persisted output rather than recorder object shape.
def _started_snapshot(logger) -> ActiveRunSnapshot:
    logger.start_recording()
    snapshot = logger._session_snapshot()
    assert snapshot is not None
    return snapshot


def _started_snapshot_with_sample(logger) -> ActiveRunSnapshot:
    snapshot = _started_snapshot(logger)
    logger._sample_flush.append_records(
        snapshot.run_id,
        snapshot.start_time_utc,
        snapshot.start_mono_s,
    )
    return snapshot


def test_build_sample_records_uses_only_active_clients(make_logger) -> None:
    logger = make_logger()

    rows = logger._sample_flush.build_sample_records(
        run_id="run-1",
        t_s=1.0,
        timestamp_utc="2026-02-16T12:00:00+00:00",
    )

    assert len(rows) == 1
    assert rows[0].client_id == "active"
    assert rows[0].client_name == "front-left wheel"
    assert rows[0].location == "front_left_wheel"
    peaks = rows[0].top_peaks
    assert peaks
    assert peaks[0].hz == 15.0
    assert peaks[0].amp == 0.12
    assert peaks[0].vibration_strength_db == 22.0
    assert peaks[0].strength_bucket == "l2"
    assert rows[0].strength_peak_amp_g == 0.15
    assert rows[0].strength_floor_amp_g == 0.003


def test_build_sample_records_caps_combined_top_peak_list(make_logger, fake_registry) -> None:
    active = fake_registry.get("active")
    assert active is not None
    active.latest_metrics["combined"]["strength_metrics"]["top_peaks"] = [
        {"hz": float(i + 1), "amp": 0.2, "vibration_strength_db": 22.0, "strength_bucket": "l2"}
        for i in range(12)
    ]
    active.latest_metrics["x"]["peaks"] = [{"hz": float(i + 1), "amp": 0.1} for i in range(6)]

    logger = make_logger(registry=fake_registry)

    rows = logger._sample_flush.build_sample_records(
        run_id="run-1",
        t_s=1.0,
        timestamp_utc="2026-02-16T12:00:00+00:00",
    )

    assert len(rows[0].top_peaks) == 8


@pytest.mark.parametrize(
    (
        "gps_speed_mps",
        "override_speed_mps",
        "resolved_source",
        "expected_source",
        "expected_speed_kmh",
    ),
    [
        (10.0, 20.0, None, "manual", 20.0 * 3.6),
        (10.0, None, "gps", "gps", 10.0 * 3.6),
        (10.0, None, "fallback_manual", "fallback_manual", 10.0 * 3.6),
        (None, None, None, "none", None),
    ],
)
def test_speed_source_reports(
    make_logger,
    fake_gps_monitor,
    gps_speed_mps: float | None,
    override_speed_mps: float | None,
    resolved_source: str | None,
    expected_source: str,
    expected_speed_kmh: float | None,
) -> None:
    """speed_source should reflect manual override, GPS, or missing speed state."""
    fake_gps_monitor.speed_mps = gps_speed_mps
    fake_gps_monitor.override_speed_mps = override_speed_mps
    fake_gps_monitor.resolved_source = resolved_source
    fake_gps_monitor.effective_speed_mps = (
        override_speed_mps if override_speed_mps is not None else gps_speed_mps
    )

    logger = make_logger(gps_monitor=fake_gps_monitor)

    rows = logger._sample_flush.build_sample_records(
        run_id="run-1",
        t_s=1.0,
        timestamp_utc="2026-02-16T12:00:00+00:00",
    )

    assert len(rows) == 1
    assert rows[0].speed_source == expected_source
    if expected_speed_kmh is None:
        assert rows[0].speed_kmh is None
    else:
        assert rows[0].speed_kmh == pytest.approx(expected_speed_kmh, abs=0.01)


def test_stop_without_samples_does_not_persist_history_run(make_logger, fake_history_db) -> None:
    logger = make_logger(history_db=fake_history_db)

    logger.start_recording()
    logger.stop_recording()

    assert fake_history_db.create_calls == []
    assert fake_history_db.append_calls == []
    assert fake_history_db.finalize_calls == []


def test_append_records_ignores_stale_recent_metrics_without_new_frames(
    make_logger,
    fake_history_db,
) -> None:
    logger = make_logger(history_db=fake_history_db)

    snapshot = _started_snapshot(logger)
    run_id = snapshot.run_id
    start_time_utc = snapshot.start_time_utc
    start_mono = snapshot.start_mono_s
    stale_rows = logger._sample_flush.build_sample_records(
        run_id=run_id,
        t_s=0.25,
        timestamp_utc="2026-02-16T12:00:00+00:00",
    )

    timed_out = logger._sample_flush.append_records(
        run_id,
        start_time_utc,
        start_mono,
        prebuilt_rows=stale_rows,
    )

    assert timed_out is False
    assert fake_history_db.create_calls == []
    assert fake_history_db.append_calls == []
    assert fake_history_db.finalize_calls == []


def test_history_run_created_on_first_sample_append(make_logger, fake_history_db) -> None:
    logger = make_logger(history_db=fake_history_db)

    snapshot = _started_snapshot(logger)
    run_id = snapshot.run_id
    start_time_utc = snapshot.start_time_utc
    start_mono = snapshot.start_mono_s

    timed_out = logger._sample_flush.append_records(
        run_id,
        start_time_utc,
        start_mono,
    )

    assert timed_out is False
    assert fake_history_db.create_calls == [(run_id, start_time_utc)]
    assert fake_history_db.append_calls == [(run_id, 1)]


def test_stop_recording_flushes_first_pending_sample_batch(
    make_logger,
    fake_history_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = make_logger(history_db=fake_history_db)
    monkeypatch.setattr(logger, "schedule_post_analysis", lambda _run_id: None)

    logger.start_recording()
    active = logger.registry.get("active")
    assert active is not None
    active.frames_total = 1

    logger.stop_recording()

    run_id, start_time_utc = fake_history_db.create_calls[-1]
    assert fake_history_db.create_calls == [(run_id, start_time_utc)]
    assert fake_history_db.append_calls == [(run_id, 1)]
    assert fake_history_db.finalize_calls == [run_id]


def test_stop_recording_salvages_final_batch_when_recent_window_is_too_strict(
    make_logger,
    fake_history_db,
    fake_registry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _LateMetricsProcessor:
        def __init__(self) -> None:
            self._refreshed = False

        def flush_client_buffer(self, client_id: str, *, reason: str = "sensor reset") -> None:
            return None

        def latest_sample_xyz(self, client_id: str):
            return (0.01, 0.02, 0.03)

        def latest_sample_rate_hz(self, client_id: str):
            return 800

        def latest_analysis_time_range(self, client_id: str):
            return None

        def compute_metrics(self, client_id: str, sample_rate_hz: int | None = None):
            self._refreshed = True
            return self.latest_metrics(client_id)

        def latest_metrics(self, client_id: str):
            record = fake_registry.get(client_id)
            if record is None:
                return {}
            if not self._refreshed:
                return {"combined": {"peaks": []}}
            return record.latest_metrics

        def clients_with_recent_data(
            self,
            client_ids: list[str],
            max_age_s: float = 3.0,
        ) -> list[str]:
            if max_age_s <= 2.0:
                return []
            return list(client_ids)

    logger = make_logger(
        history_db=fake_history_db,
        registry=fake_registry,
        processor=_LateMetricsProcessor(),
    )
    monkeypatch.setattr(logger, "schedule_post_analysis", lambda _run_id: None)

    logger.start_recording()
    active = logger.registry.get("active")
    assert active is not None
    active.frames_total = 1

    logger.stop_recording()

    run_id, start_time_utc = fake_history_db.create_calls[-1]
    assert fake_history_db.create_calls == [(run_id, start_time_utc)]
    assert fake_history_db.append_calls == [(run_id, 1)]
    assert fake_history_db.finalize_calls == [run_id]


def test_start_recording_rollover_flushes_first_pending_sample_batch(
    make_logger,
    fake_history_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduled: list[str] = []
    logger = make_logger(history_db=fake_history_db)
    monkeypatch.setattr(logger, "schedule_post_analysis", scheduled.append)

    initial_status = logger.start_recording()
    initial_run_id = str(initial_status.run_id)
    active = logger.registry.get("active")
    assert active is not None
    active.frames_total = 1

    next_status = logger.start_recording()

    created_run_id, start_time_utc = fake_history_db.create_calls[-1]
    assert created_run_id == initial_run_id
    assert fake_history_db.create_calls == [(created_run_id, start_time_utc)]
    assert fake_history_db.append_calls == [(created_run_id, 1)]
    assert fake_history_db.finalize_calls == [created_run_id]
    assert scheduled == [created_run_id]
    assert next_status.run_id != created_run_id


def test_finalize_preserves_run_metadata_from_recording_start(
    make_logger,
    fake_history_db,
    mutable_fake_settings,
) -> None:
    logger = make_logger(settings_reader=mutable_fake_settings, history_db=fake_history_db)

    snapshot = _started_snapshot_with_sample(logger)
    run_id = snapshot.run_id

    mutable_fake_settings.values["tire_width_mm"] = 315.0
    logger.stop_recording()

    assert fake_history_db.updated_metadata
    updated_run_id, metadata = fake_history_db.updated_metadata[-1]
    assert updated_run_id == run_id
    assert metadata.analysis_settings.tire_width_mm == 285.0


def test_append_records_surfaces_create_run_failure_in_status(
    make_logger,
    failing_create_run_db,
) -> None:
    logger = make_logger(history_db=failing_create_run_db)

    _started_snapshot_with_sample(logger)
    status = logger.status()

    assert status.write_error is not None
    assert "history create_run failed" in str(status.write_error)
    assert "create_run boom" in str(status.write_error)


def test_append_records_clears_write_error_after_successful_retry(
    make_logger,
    failing_append_once_db,
) -> None:
    logger = make_logger(history_db=failing_append_once_db)

    snapshot = _started_snapshot_with_sample(logger)
    failed_status = logger.status()
    assert failed_status.write_error is not None
    assert "history append_samples failed" in str(failed_status.write_error)

    logger._sample_flush.append_records(
        snapshot.run_id,
        snapshot.start_time_utc,
        snapshot.start_mono_s,
    )
    recovered_status = logger.status()
    assert recovered_status.write_error is None


def test_append_records_reports_timeout_when_no_data_for_threshold(
    make_logger,
    no_active_registry,
) -> None:
    logger = make_logger(registry=no_active_registry)

    snapshot = _started_snapshot(logger)
    run_id = snapshot.run_id
    start_time_utc = snapshot.start_time_utc
    start_mono = snapshot.start_mono_s
    logger._lifecycle.last_data_progress_mono_s = 0.0

    timed_out = logger._sample_flush.append_records(
        run_id,
        start_time_utc,
        start_mono,
    )

    assert timed_out is True


def test_append_records_does_not_timeout_on_brief_gap(
    make_logger,
    no_active_registry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = make_logger(registry=no_active_registry)

    snapshot = _started_snapshot(logger)
    run_id = snapshot.run_id
    start_time_utc = snapshot.start_time_utc
    start_mono = snapshot.start_mono_s
    monkeypatch.setattr("vibesensor.use_cases.run.logger.time.monotonic", lambda: 100.0)
    logger._lifecycle.last_data_progress_mono_s = 95.0

    timed_out = logger._sample_flush.append_records(
        run_id,
        start_time_utc,
        start_mono,
    )

    assert timed_out is False
