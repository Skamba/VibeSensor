from __future__ import annotations

from unittest.mock import ANY

import pytest
from test_support.synthetic_samples import axis_spectrum

from vibesensor.domain.run_status import RunStatus
from vibesensor.history.history_db import HistoryDB
from vibesensor.recording.lifecycle_state import ActiveRunSnapshot


# Remaining private seam: these tests need a deterministic active recorder plus
# exactly one flush without running the async loop. Assertions stay on emitted
# samples, status, and persisted output rather than recorder object shape.
def _stored_runs(db: HistoryDB) -> list[tuple[str, str, int, RunStatus]]:
    return [(r.run_id, r.start_time_utc, r.sample_count, r.status) for r in db.list_runs()]


def _started_snapshot(logger) -> ActiveRunSnapshot:
    logger.start_recording()
    snapshot = logger._lifecycle.snapshot()
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
    active.latest_metrics["x"] = axis_spectrum(*((float(i + 10), 0.1) for i in range(6)))

    logger = make_logger(registry=fake_registry)

    rows = logger._sample_flush.build_sample_records(
        run_id="run-1",
        t_s=1.0,
        timestamp_utc="2026-02-16T12:00:00+00:00",
    )

    assert len(rows[0].top_peaks) == 8


@pytest.mark.parametrize(
    ("configure", "expected_source", "expected_speed_kmh"),
    [
        pytest.param(
            lambda rig: (rig.gps_speed(10.0), rig.manual(72.0)), "manual", 72.0, id="manual"
        ),
        pytest.param(lambda rig: rig.gps_speed(10.0), "gps", 36.0, id="gps"),
        pytest.param(lambda rig: rig.manual_fallback(36.0), "fallback_manual", 36.0, id="fallback"),
        pytest.param(lambda rig: setattr(rig.gps, "gps_enabled", False), "none", None, id="none"),
    ],
)
def test_speed_source_reports(
    make_logger,
    speed_rig,
    configure,
    expected_source: str,
    expected_speed_kmh: float | None,
) -> None:
    """speed_source should reflect manual override, GPS, fallback, or missing speed."""
    configure(speed_rig)
    logger = make_logger(gps_monitor=speed_rig.observation)

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


def test_stop_without_samples_records_the_run_in_history_with_an_error(
    make_logger, history_db
) -> None:
    # A run that captured nothing (sensor gone, or its timestamps unusable) must
    # not vanish: History shows it with the reason, and so does the recorder status.
    logger = make_logger(history_db=history_db)

    run_id = logger.start_recording().run_id
    logger.stop_recording()
    assert logger.post_analysis.wait(timeout_s=10.0)

    run = history_db.get_run(run_id)
    assert run is not None
    assert run.status == "error"
    assert run.error_message == "No samples collected during run"
    status = logger.status()
    assert status.last_completed_run_id == run_id
    assert status.last_completed_run_error == "No samples collected during run"


def test_append_records_ignores_stale_recent_metrics_without_new_frames(
    make_logger,
    history_db,
) -> None:
    logger = make_logger(history_db=history_db)

    snapshot = _started_snapshot(logger)
    run_id = snapshot.run_id
    start_time_utc = snapshot.start_time_utc
    start_mono = snapshot.start_mono_s
    stale_rows = logger._sample_flush.build_sample_records(
        run_id=run_id,
        t_s=0.25,
        timestamp_utc="2026-02-16T12:00:00+00:00",
    )

    auto_stop_reason = logger._sample_flush.append_records(
        run_id,
        start_time_utc,
        start_mono,
        prebuilt_rows=stale_rows,
    )

    assert auto_stop_reason is None
    assert history_db.list_runs() == []


def test_history_run_created_on_first_sample_append(make_logger, history_db) -> None:
    logger = make_logger(history_db=history_db)

    snapshot = _started_snapshot(logger)
    run_id = snapshot.run_id
    start_time_utc = snapshot.start_time_utc
    start_mono = snapshot.start_mono_s

    auto_stop_reason = logger._sample_flush.append_records(
        run_id,
        start_time_utc,
        start_mono,
    )

    assert auto_stop_reason is None
    assert _stored_runs(history_db) == [(run_id, start_time_utc, 1, RunStatus.RECORDING)]


def test_stop_recording_flushes_first_pending_sample_batch(
    make_logger,
    history_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = make_logger(history_db=history_db)
    monkeypatch.setattr(logger.post_analysis, "schedule", lambda _run_id: None)

    run_id = logger.start_recording().run_id
    active = logger.registry.get("active")
    assert active is not None
    active.frames_total = 1

    logger.stop_recording()

    assert _stored_runs(history_db) == [(run_id, ANY, 1, RunStatus.ANALYZING)]


def test_stop_recording_salvages_final_batch_when_recent_window_is_too_strict(
    make_logger,
    history_db,
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
        history_db=history_db,
        registry=fake_registry,
        processor=_LateMetricsProcessor(),
    )
    monkeypatch.setattr(logger.post_analysis, "schedule", lambda _run_id: None)

    run_id = logger.start_recording().run_id
    active = logger.registry.get("active")
    assert active is not None
    active.frames_total = 1

    logger.stop_recording()

    assert _stored_runs(history_db) == [(run_id, ANY, 1, RunStatus.ANALYZING)]


def test_start_recording_rollover_flushes_first_pending_sample_batch(
    make_logger,
    history_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduled: list[str] = []
    logger = make_logger(history_db=history_db)
    monkeypatch.setattr(logger.post_analysis, "schedule", scheduled.append)

    initial_status = logger.start_recording()
    initial_run_id = str(initial_status.run_id)
    active = logger.registry.get("active")
    assert active is not None
    active.frames_total = 1

    next_status = logger.start_recording()

    assert _stored_runs(history_db) == [(initial_run_id, ANY, 1, RunStatus.ANALYZING)]
    assert scheduled == [initial_run_id]
    assert next_status.run_id != initial_run_id


def test_finalize_preserves_run_metadata_from_recording_start(
    make_logger,
    history_db,
    mutable_fake_settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = make_logger(settings_reader=mutable_fake_settings, history_db=history_db)
    monkeypatch.setattr(logger.post_analysis, "schedule", lambda _run_id: None)

    snapshot = _started_snapshot_with_sample(logger)
    run_id = snapshot.run_id

    mutable_fake_settings.values["tire_width_mm"] = 315.0
    logger.stop_recording()

    metadata = history_db.get_run_metadata(run_id)
    assert metadata is not None
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

    auto_stop_reason = logger._sample_flush.append_records(
        run_id,
        start_time_utc,
        start_mono,
    )

    assert auto_stop_reason == "no_data_timeout"


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
    monkeypatch.setattr("vibesensor.recording.recorder.time.monotonic", lambda: 100.0)
    logger._lifecycle.last_data_progress_mono_s = 95.0

    auto_stop_reason = logger._sample_flush.append_records(
        run_id,
        start_time_utc,
        start_mono,
    )

    assert auto_stop_reason is None


def test_written_rows_count_as_data_progress(make_logger, history_db) -> None:
    logger = make_logger(history_db=history_db)
    snapshot = _started_snapshot(logger)
    # The last progress is far in the past, but this flush writes rows.
    logger._lifecycle.last_data_progress_mono_s = 0.0

    auto_stop_reason = logger._sample_flush.append_records(
        snapshot.run_id,
        snapshot.start_time_utc,
        snapshot.start_mono_s,
    )

    assert auto_stop_reason is None
    assert logger.status().enabled is True
