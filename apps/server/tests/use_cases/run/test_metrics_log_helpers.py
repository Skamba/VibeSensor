from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_support.core import wait_until
from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
from vibesensor.domain import AnalysisSettingsSnapshot, CarSnapshot
from vibesensor.shared.types.history_records import AnalyzingRunHealth
from vibesensor.use_cases.run import _recorder_runtime
from vibesensor.use_cases.run._recorder_types import _build_run_metadata_record
from vibesensor.use_cases.run.lifecycle_state import ActiveRunSnapshot
from vibesensor.use_cases.run.post_analysis import PostAnalysisHealthSnapshot


class _NullDB:
    """Stub DB for tests that need a non-None history_db without real DB ops."""

    def analyzing_run_health(self):
        return AnalyzingRunHealth(analyzing_run_count=0, analyzing_oldest_age_s=None)


def _started_snapshot(logger) -> ActiveRunSnapshot:
    logger.start_recording()
    snapshot = logger._session_snapshot()
    assert snapshot is not None
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


def test_build_sample_records_caps_combined_and_axis_peak_lists(make_logger, fake_registry) -> None:
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
    ("gps_speed_mps", "override_speed_mps", "expected_source", "expected_speed_kmh"),
    [
        (10.0, 20.0, "manual", 20.0 * 3.6),
        (10.0, None, "gps", 10.0 * 3.6),
        (None, None, "none", None),
    ],
)
def test_speed_source_reports(
    make_logger,
    fake_gps_monitor,
    gps_speed_mps: float | None,
    override_speed_mps: float | None,
    expected_source: str,
    expected_speed_kmh: float | None,
) -> None:
    """speed_source should reflect manual override, GPS, or missing speed state."""
    fake_gps_monitor.speed_mps = gps_speed_mps
    fake_gps_monitor.override_speed_mps = override_speed_mps
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

    snapshot = _started_snapshot(logger)
    run_id = snapshot.run_id
    start_time_utc = snapshot.start_time_utc
    start_mono = snapshot.start_mono_s
    logger._sample_flush.append_records(run_id, start_time_utc, start_mono)

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

    snapshot = _started_snapshot(logger)
    run_id = snapshot.run_id
    start_time_utc = snapshot.start_time_utc
    start_mono = snapshot.start_mono_s

    logger._sample_flush.append_records(run_id, start_time_utc, start_mono)
    status = logger.status()

    assert status.write_error is not None
    assert "history create_run failed" in str(status.write_error)
    assert "create_run boom" in str(status.write_error)


def test_append_records_clears_write_error_after_successful_retry(
    make_logger,
    failing_append_once_db,
) -> None:
    logger = make_logger(history_db=failing_append_once_db)

    snapshot = _started_snapshot(logger)
    run_id = snapshot.run_id
    start_time_utc = snapshot.start_time_utc
    start_mono = snapshot.start_mono_s

    logger._sample_flush.append_records(run_id, start_time_utc, start_mono)
    failed_status = logger.status()
    assert failed_status.write_error is not None
    assert "history append_samples failed" in str(failed_status.write_error)

    logger._sample_flush.append_records(run_id, start_time_utc, start_mono)
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


def test_stop_recording_does_not_block_on_post_analysis(
    make_logger,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stopping capture should be fast even when analysis is slow.

    Post-analysis belongs in background processing because users expect stop controls to respond
    promptly. This test simulates a slow summarizer and requires stop_recording to return quickly
    while analysis completes asynchronously afterward.
    """
    history_db = create_history_persistence_adapters(tmp_path / "history.db")
    summary_started = threading.Event()
    allow_summary_finish = threading.Event()

    def _slow_analysis_runner(_run):
        summary_started.set()
        assert allow_summary_finish.wait(timeout=5.0)
        return make_persisted_analysis(
            {
                "findings": [],
                "top_causes": [],
                "analysis_metadata": {},
                "case_id": "mock-case",
            }
        )

    monkeypatch.setattr(
        "vibesensor.use_cases.run.logger.build_post_analysis_summary",
        _slow_analysis_runner,
    )
    logger = make_logger(history_db=history_db.run_repository)

    snapshot = _started_snapshot(logger)
    run_id = snapshot.run_id
    start_time_utc = snapshot.start_time_utc
    start_mono = snapshot.start_mono_s
    logger._sample_flush.append_records(run_id, start_time_utc, start_mono)

    started = time.monotonic()
    logger.stop_recording()
    elapsed = time.monotonic() - started

    # stop_recording() must return quickly; summary runs in a worker thread.
    # 5.0s threshold guards against blocking; not a performance target.
    assert elapsed < 5.0, f"stop_recording() blocked for {elapsed:.2f}s (expected < 5.0s)"
    assert summary_started.wait(timeout=2.0)
    allow_summary_finish.set()

    def _status():
        run = history_db.run_repository.get_run(run_id)
        return run.status.value if run is not None else None

    assert wait_until(lambda: _status() == "complete", timeout_s=5.0)


def test_post_analysis_unexpected_failure_surfaces_worker_error_status(
    make_logger,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_db = create_history_persistence_adapters(tmp_path / "history.db")

    def _failing_analysis_runner(_run) -> dict[str, object]:
        raise RuntimeError("analysis exploded")

    monkeypatch.setattr(
        "vibesensor.use_cases.run.logger.build_post_analysis_summary",
        _failing_analysis_runner,
    )
    logger = make_logger(history_db=history_db.run_repository)

    snapshot = _started_snapshot(logger)
    run_id = snapshot.run_id
    start_time_utc = snapshot.start_time_utc
    start_mono = snapshot.start_mono_s
    logger._sample_flush.append_records(run_id, start_time_utc, start_mono)

    logger.stop_recording()

    def _status():
        return logger.status().last_completed_run_error

    expected_worker_bug = "Unexpected post-analysis worker bug: analysis exploded"
    assert wait_until(lambda: _status() == expected_worker_bug, timeout_s=2.0)
    status = logger.status()
    assert status.last_completed_run_error == expected_worker_bug
    assert status.write_error == f"post-analysis worker bug for run {run_id}: analysis exploded"
    run = history_db.run_repository.get_run(run_id)
    assert run is not None
    assert run.analysis is None
    assert run.status.value == "error"
    assert run.error_message == expected_worker_bug


def test_post_analysis_burst_uses_single_daemon_worker(
    make_logger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = make_logger(history_db=_NullDB())

    active = 0
    max_active = 0
    seen: list[str] = []
    state_lock = threading.Lock()

    def _slow_post_analysis(run_id: str) -> None:
        nonlocal active, max_active
        with state_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.005)
        seen.append(run_id)
        with state_lock:
            active -= 1

    monkeypatch.setattr(logger._post_analysis, "_run_post_analysis", _slow_post_analysis)

    for idx in range(6):
        logger.schedule_post_analysis(f"run-{idx}")

    logger.wait_for_post_analysis(timeout_s=3.0)

    assert max_active == 1
    assert len(seen) == 6
    # After all work completes, the worker thread should have exited and
    # been cleared to allow a fresh thread on the next scheduling call.
    with logger._post_analysis._lock:
        worker = logger._post_analysis._analysis_thread
    assert worker is None


def test_shutdown_blocks_new_start_recording_until_wait_completes(
    make_logger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = make_logger(history_db=_NullDB())
    logger.start_recording()
    initial_run_id = logger._run_id
    assert initial_run_id is not None

    allow_wait = threading.Event()

    def _wait(timeout_s: float = 30.0) -> bool:
        assert timeout_s == 30.0
        start_result = logger.start_recording()
        assert start_result.enabled is False
        assert start_result.run_id is None
        # Session was stopped by shutdown
        assert logger._run_id is None
        allow_wait.set()
        return True

    monkeypatch.setattr(logger._post_analysis, "wait", _wait)

    assert logger.shutdown() is True
    assert allow_wait.is_set()
    restarted = logger.start_recording()
    assert restarted.enabled is True
    assert restarted.run_id is not None
    assert restarted.run_id != initial_run_id


def test_shutdown_report_exposes_timeout_state(
    make_logger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = make_logger()
    logger.start_recording()

    monkeypatch.setattr(logger._post_analysis, "wait", lambda timeout_s=30.0: False)
    monkeypatch.setattr(
        logger._post_analysis,
        "snapshot",
        lambda: PostAnalysisHealthSnapshot(
            queue_depth=2,
            active_run_id="run-slow",
            active_started_at=None,
            oldest_queued_at=time.time() - 5.0,
            max_queue_depth=2,
            last_completed_run_id=None,
            last_completed_error=None,
        ),
    )

    report = logger.shutdown_report(timeout_s=0.1)

    assert report.completed is False
    assert report.active_run_id_before_stop is not None
    assert report.analysis_queue_depth == 2
    assert report.analysis_active_run_id == "run-slow"
    assert report.final_status.enabled is False


def test_post_analysis_uses_run_language_from_metadata(
    make_logger,
    tmp_path: Path,
) -> None:
    history_db = create_history_persistence_adapters(tmp_path / "history.db")
    logger = make_logger(
        history_db=history_db.run_repository,
        language_reader=SimpleNamespace(language="nl"),
    )

    snapshot = _started_snapshot(logger)
    run_id = snapshot.run_id
    start_time_utc = snapshot.start_time_utc
    start_mono = snapshot.start_mono_s
    logger._sample_flush.append_records(run_id, start_time_utc, start_mono)

    def _analysis_runner(run):
        assert run.run_id == snapshot.run_id
        assert run.context.language == "nl"
        assert run.language == "nl"
        assert run.total_sample_count == len(run.samples)
        assert run.stride == 1
        return make_persisted_analysis(
            {
                "lang": run.language,
                "row_count": len(run.samples),
                "analysis_metadata": {
                    "analyzed_sample_count": len(run.samples),
                    "total_sample_count": run.total_sample_count,
                    "sampling_method": "full",
                },
                "run_suitability": [],
            }
        )

    logger._post_analysis._analysis_runner = _analysis_runner
    logger.stop_recording()

    def _status():
        run = history_db.run_repository.get_run(run_id)
        return run.status.value if run is not None else None

    assert wait_until(lambda: _status() == "complete", timeout_s=2.0)
    stored = history_db.run_repository.get_run(run_id).analysis
    assert stored is not None
    assert stored["lang"] == "nl"


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

    snapshot = _started_snapshot(logger)
    run_id = snapshot.run_id
    start_time_utc = snapshot.start_time_utc
    start_mono = snapshot.start_mono_s
    logger._sample_flush.append_records(run_id, start_time_utc, start_mono)
    logger.stop_recording()

    assert history_db.run_repository.get_run(run_id) is not None
    assert history_db.run_repository.get_run_samples(run_id)


def test_post_analysis_caps_sample_count_and_stores_sampling_metadata(
    make_logger,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Reduce the cap so we only need ~250 iterations instead of 13 000 (28 s -> <1 s).
    cap = 200
    monkeypatch.setattr(
        "vibesensor.use_cases.run.post_analysis_loader._MAX_POST_ANALYSIS_SAMPLES",
        cap,
    )

    history_db = create_history_persistence_adapters(tmp_path / "history.db")
    logger = make_logger(history_db=history_db.run_repository)

    snapshot = _started_snapshot(logger)
    run_id = snapshot.run_id
    start_time_utc = snapshot.start_time_utc
    start_mono = snapshot.start_mono_s
    for _ in range(cap + 50):
        logger._sample_flush.append_records(run_id, start_time_utc, start_mono)

    def _analysis_runner(run):
        assert run.run_id == snapshot.run_id
        assert run.language == "en"
        return make_persisted_analysis(
            {
                "row_count": len(run.samples),
                "analysis_metadata": {
                    "analyzed_sample_count": len(run.samples),
                    "total_sample_count": run.total_sample_count,
                    "sampling_method": ("full" if run.stride == 1 else f"stride_{run.stride}"),
                },
                "run_suitability": (
                    [
                        {
                            "check_key": "SUITABILITY_CHECK_ANALYSIS_SAMPLING",
                            "state": "warn",
                            "explanation": f"stride={run.stride}",
                        }
                    ]
                    if run.stride > 1
                    else []
                ),
            }
        )

    logger._post_analysis._analysis_runner = _analysis_runner
    logger.stop_recording()

    def _status():
        run = history_db.run_repository.get_run(run_id)
        return run.status.value if run is not None else None

    assert wait_until(lambda: _status() == "complete", timeout_s=3.0)
    stored = history_db.run_repository.get_run(run_id).analysis
    assert stored is not None
    assert stored["row_count"] <= cap
    assert stored["analysis_metadata"]["total_sample_count"] >= stored["row_count"]
    assert stored["analysis_metadata"]["sampling_method"].startswith("stride_")
    suitability_checks = {str(item.get("check_key")) for item in stored.get("run_suitability", [])}
    assert "SUITABILITY_CHECK_ANALYSIS_SAMPLING" in suitability_checks


@pytest.mark.asyncio
async def test_run_offloads_flush_cycle_with_to_thread(
    make_logger,
    fake_history_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = make_logger(history_db=fake_history_db)

    logger.start_recording()
    captured: dict[str, object] = {}

    async def _fake_to_thread(func: object, *args: object, **kwargs: object) -> tuple[None, bool]:
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return None, False

    async def _cancel_sleep(_interval: float) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(
        "vibesensor.use_cases.run._recorder_runtime.asyncio.to_thread",
        _fake_to_thread,
    )
    monkeypatch.setattr(
        "vibesensor.use_cases.run._recorder_runtime.asyncio.sleep",
        _cancel_sleep,
    )

    with pytest.raises(asyncio.CancelledError):
        await logger.run()

    assert captured.get("func") == _recorder_runtime._flush_active_run_tick
    assert captured.get("args") == (logger,)
