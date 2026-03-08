from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest
from _test_helpers import wait_until

from vibesensor.history_db import HistoryDB
from vibesensor.metrics_log.sample_builder import safe_metric

# -- MetricsLogger._safe_metric ------------------------------------------------


@pytest.mark.parametrize(
    ("metrics", "axis", "key", "expected"),
    [
        pytest.param(
            {"x": {"rms": 0.05, "p2p": 0.12}},
            "x",
            "rms",
            0.05,
            marks=pytest.mark.smoke,
        ),
        ({"x": {"rms": 0.05}}, "y", "rms", None),
        ({"x": {"rms": 0.05}}, "x", "p2p", None),
        ({"x": {"rms": float("nan")}}, "x", "rms", None),
        ({"x": {"rms": float("inf")}}, "x", "rms", None),
        ({"x": "not_a_dict"}, "x", "rms", None),
        ({"x": {"rms": "abc"}}, "x", "rms", None),
    ],
)
def test_safe_metric(metrics: dict, axis: str, key: str, expected: float | None) -> None:
    assert safe_metric(metrics, axis, key) == expected


class _ReverseOnlySamples:
    def __init__(self, samples: list[dict[str, object]]) -> None:
        self._samples = samples

    def __len__(self) -> int:
        return len(self._samples)

    def __iter__(self):
        raise AssertionError("analysis_snapshot should not iterate all live samples")

    def __reversed__(self):
        return reversed(self._samples)


def test_build_sample_records_uses_only_active_clients(make_logger) -> None:
    logger = make_logger()

    rows = logger._build_sample_records(
        run_id="run-1",
        t_s=1.0,
        timestamp_utc="2026-02-16T12:00:00+00:00",
    )

    assert len(rows) == 1
    assert rows[0]["client_id"] == "active"
    assert rows[0]["client_name"] == "front-left wheel"
    assert rows[0]["location"] == "front_left_wheel"
    peaks = rows[0]["top_peaks"]
    assert isinstance(peaks, list) and peaks
    assert peaks[0]["hz"] == 15.0
    assert peaks[0]["amp"] == 0.12
    assert peaks[0]["vibration_strength_db"] == 22.0
    assert peaks[0]["strength_bucket"] == "l2"
    assert rows[0]["top_peaks_x"] == [{"hz": 15.0, "amp": 0.12}]
    assert rows[0]["top_peaks_y"] == [{"hz": 16.0, "amp": 0.08}]
    assert rows[0]["top_peaks_z"] == [{"hz": 14.0, "amp": 0.07}]
    assert rows[0]["strength_peak_amp_g"] == 0.15
    assert rows[0]["strength_floor_amp_g"] == 0.003


def test_build_sample_records_caps_combined_and_axis_peak_lists(make_logger, fake_registry) -> None:
    active = fake_registry.get("active")
    assert active is not None
    active.latest_metrics["strength_metrics"]["top_peaks"] = [  # type: ignore[index]
        {"hz": float(i + 1), "amp": 0.2, "vibration_strength_db": 22.0, "strength_bucket": "l2"}
        for i in range(12)
    ]
    active.latest_metrics["x"]["peaks"] = [  # type: ignore[index]
        {"hz": float(i + 1), "amp": 0.1} for i in range(6)
    ]

    logger = make_logger(registry=fake_registry)

    rows = logger._build_sample_records(
        run_id="run-1",
        t_s=1.0,
        timestamp_utc="2026-02-16T12:00:00+00:00",
    )

    assert len(rows[0]["top_peaks"]) == 8
    assert len(rows[0]["top_peaks_x"]) == 3


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

    rows = logger._build_sample_records(
        run_id="run-1",
        t_s=1.0,
        timestamp_utc="2026-02-16T12:00:00+00:00",
    )

    assert len(rows) == 1
    assert rows[0]["speed_source"] == expected_source
    if expected_speed_kmh is None:
        assert rows[0]["speed_kmh"] is None
    else:
        assert rows[0]["speed_kmh"] == pytest.approx(expected_speed_kmh, abs=0.01)


def test_stop_without_samples_does_not_persist_history_run(make_logger, fake_history_db) -> None:
    logger = make_logger(history_db=fake_history_db)

    logger.start_logging()
    logger.stop_logging()

    assert fake_history_db.create_calls == []
    assert fake_history_db.append_calls == []
    assert fake_history_db.finalize_calls == []


def test_append_records_ignores_stale_recent_metrics_without_new_frames(
    make_logger, fake_history_db
) -> None:
    logger = make_logger(history_db=fake_history_db)

    logger.start_logging()
    snapshot = logger._session_snapshot()
    assert snapshot is not None
    run_id, start_time_utc, start_mono, generation = snapshot
    stale_rows = logger._build_sample_records(
        run_id=run_id,
        t_s=0.25,
        timestamp_utc="2026-02-16T12:00:00+00:00",
    )

    timed_out = logger._append_records(
        run_id,
        start_time_utc,
        start_mono,
        session_generation=generation,
        prebuilt_rows=stale_rows,
    )

    assert timed_out is False
    assert fake_history_db.create_calls == []
    assert fake_history_db.append_calls == []
    assert fake_history_db.finalize_calls == []


def test_history_run_created_on_first_sample_append(make_logger, fake_history_db) -> None:
    logger = make_logger(history_db=fake_history_db)

    logger.start_logging()
    snapshot = logger._session_snapshot()
    assert snapshot is not None
    run_id, start_time_utc, start_mono, generation = snapshot

    timed_out = logger._append_records(
        run_id,
        start_time_utc,
        start_mono,
        session_generation=generation,
    )

    assert timed_out is False
    assert fake_history_db.create_calls == [(run_id, start_time_utc)]
    assert fake_history_db.append_calls == [(run_id, 1)]


def test_stop_logging_flushes_first_pending_sample_batch(
    make_logger, fake_history_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    logger = make_logger(history_db=fake_history_db)
    monkeypatch.setattr(logger, "schedule_post_analysis", lambda _run_id: None)

    logger.start_logging()
    active = logger.registry.get("active")
    assert active is not None
    active.frames_total = 1

    logger.stop_logging()

    run_id, start_time_utc = fake_history_db.create_calls[-1]
    assert fake_history_db.create_calls == [(run_id, start_time_utc)]
    assert fake_history_db.append_calls == [(run_id, 1)]
    assert fake_history_db.finalize_calls == [run_id]


def test_start_logging_rollover_flushes_first_pending_sample_batch(
    make_logger, fake_history_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    scheduled: list[str] = []
    logger = make_logger(history_db=fake_history_db)
    monkeypatch.setattr(logger, "schedule_post_analysis", scheduled.append)

    initial_status = logger.start_logging()
    initial_run_id = str(initial_status["run_id"])
    active = logger.registry.get("active")
    assert active is not None
    active.frames_total = 1

    next_status = logger.start_logging()

    created_run_id, start_time_utc = fake_history_db.create_calls[-1]
    assert created_run_id == initial_run_id
    assert fake_history_db.create_calls == [(created_run_id, start_time_utc)]
    assert fake_history_db.append_calls == [(created_run_id, 1)]
    assert fake_history_db.finalize_calls == [created_run_id]
    assert scheduled == [created_run_id]
    assert next_status["run_id"] != created_run_id


def test_finalize_refreshes_run_metadata_from_latest_settings(
    make_logger, fake_history_db, mutable_fake_settings
) -> None:
    logger = make_logger(analysis_settings=mutable_fake_settings, history_db=fake_history_db)

    logger.start_logging()
    snapshot = logger._session_snapshot()
    assert snapshot is not None
    run_id, start_time_utc, start_mono, generation = snapshot
    logger._append_records(run_id, start_time_utc, start_mono, session_generation=generation)

    mutable_fake_settings.values["tire_width_mm"] = 315.0
    logger.stop_logging()

    assert fake_history_db.updated_metadata
    updated_run_id, metadata = fake_history_db.updated_metadata[-1]
    assert updated_run_id == run_id
    assert metadata["tire_width_mm"] == 315.0


def test_append_records_surfaces_create_run_failure_in_status(
    make_logger, failing_create_run_db
) -> None:
    logger = make_logger(history_db=failing_create_run_db)

    logger.start_logging()
    snapshot = logger._session_snapshot()
    assert snapshot is not None
    run_id, start_time_utc, start_mono, generation = snapshot

    logger._append_records(run_id, start_time_utc, start_mono, session_generation=generation)
    status = logger.status()

    assert status["write_error"] is not None
    assert "history create_run failed" in str(status["write_error"])
    assert "create_run boom" in str(status["write_error"])


def test_append_records_clears_write_error_after_successful_retry(
    make_logger, failing_append_once_db
) -> None:
    logger = make_logger(history_db=failing_append_once_db)

    logger.start_logging()
    snapshot = logger._session_snapshot()
    assert snapshot is not None
    run_id, start_time_utc, start_mono, generation = snapshot

    logger._append_records(run_id, start_time_utc, start_mono, session_generation=generation)
    failed_status = logger.status()
    assert failed_status["write_error"] is not None
    assert "history append_samples failed" in str(failed_status["write_error"])

    logger._append_records(run_id, start_time_utc, start_mono, session_generation=generation)
    recovered_status = logger.status()
    assert recovered_status["write_error"] is None


def test_append_records_reports_timeout_when_no_data_for_threshold(
    make_logger, no_active_registry
) -> None:
    logger = make_logger(registry=no_active_registry)

    logger.start_logging()
    snapshot = logger._session_snapshot()
    assert snapshot is not None
    run_id, start_time_utc, start_mono, generation = snapshot
    logger._last_data_progress_mono_s = 0.0

    timed_out = logger._append_records(
        run_id,
        start_time_utc,
        start_mono,
        session_generation=generation,
    )

    assert timed_out is True


def test_append_records_does_not_timeout_on_brief_gap(
    make_logger, no_active_registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    logger = make_logger(registry=no_active_registry)

    logger.start_logging()
    snapshot = logger._session_snapshot()
    assert snapshot is not None
    run_id, start_time_utc, start_mono, generation = snapshot
    monkeypatch.setattr("vibesensor.metrics_log.logger.time.monotonic", lambda: 100.0)
    logger._last_data_progress_mono_s = 95.0

    timed_out = logger._append_records(
        run_id,
        start_time_utc,
        start_mono,
        session_generation=generation,
    )

    assert timed_out is False


def test_stop_logging_does_not_block_on_post_analysis(
    make_logger, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stopping capture should be fast even when analysis is slow.

    Post-analysis belongs in background processing because users expect stop controls to respond
    promptly. This test simulates a slow summarizer and requires stop_logging to return quickly
    while analysis completes asynchronously afterward.
    """
    history_db = HistoryDB(tmp_path / "history.db")
    logger = make_logger(history_db=history_db)

    logger.start_logging()
    snapshot = logger._session_snapshot()
    assert snapshot is not None
    run_id, start_time_utc, start_mono, generation = snapshot
    logger._append_records(run_id, start_time_utc, start_mono, session_generation=generation)

    summary_started = threading.Event()
    allow_summary_finish = threading.Event()

    def _slow_summary(*args, **kwargs):
        summary_started.set()
        assert allow_summary_finish.wait(timeout=5.0)
        return {"summary": "ok"}

    monkeypatch.setattr("vibesensor.analysis.summarize_run_data", _slow_summary)
    started = time.monotonic()
    logger.stop_logging()
    elapsed = time.monotonic() - started

    # stop_logging() must return quickly; summary runs in a worker thread
    assert elapsed < 0.45, f"stop_logging() blocked for {elapsed:.2f}s (expected < 0.45s)"
    assert summary_started.wait(timeout=2.0)
    allow_summary_finish.set()
    assert wait_until(lambda: history_db.get_run_status(run_id) == "complete", timeout_s=5.0)


def test_post_analysis_failure_sets_persistent_error_status(
    make_logger, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    history_db = HistoryDB(tmp_path / "history.db")
    logger = make_logger(history_db=history_db)

    logger.start_logging()
    snapshot = logger._session_snapshot()
    assert snapshot is not None
    run_id, start_time_utc, start_mono, generation = snapshot
    logger._append_records(run_id, start_time_utc, start_mono, session_generation=generation)

    def _failing_summary(*args, **kwargs):
        raise RuntimeError("analysis exploded")

    monkeypatch.setattr("vibesensor.analysis.summarize_run_data", _failing_summary)
    logger.stop_logging()

    assert wait_until(lambda: history_db.get_run_status(run_id) == "error", timeout_s=2.0)
    run = history_db.get_run(run_id)
    assert run is not None
    assert "analysis exploded" in str(run.get("error_message", ""))


def test_post_analysis_burst_uses_single_daemon_worker(
    make_logger, monkeypatch: pytest.MonkeyPatch
) -> None:
    logger = make_logger(history_db=object())

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


def test_analysis_snapshot_isolated_per_logging_run(make_logger) -> None:
    logger = make_logger()

    logger.start_logging()
    logger.live_analysis.extend_rows([{"run_marker": "run1"}], live_t_s=0.0)
    logger.stop_logging()

    logger.start_logging()
    metadata, samples = logger.analysis_snapshot()

    assert metadata["run_id"] != "live"
    assert all(sample.get("run_marker") != "run1" for sample in samples)


def test_analysis_snapshot_reads_tail_without_full_iteration(make_logger) -> None:
    logger = make_logger()

    logger.live_analysis._samples = _ReverseOnlySamples([{"idx": idx} for idx in range(10)])  # type: ignore[assignment]

    _, samples = logger.analysis_snapshot(max_rows=3)

    assert [sample["idx"] for sample in samples] == [7, 8, 9]


def test_live_samples_are_pruned_to_recent_window(make_logger) -> None:
    logger = make_logger()

    with logger.live_analysis._lock:
        logger.live_analysis._samples.extend(
            [
                {"t_s": 0.1, "sample_id": "old"},
                {"t_s": 1.0, "sample_id": "edge"},
                {"t_s": 1.7, "sample_id": "recent-a"},
                {"t_s": 2.9, "sample_id": "recent-b"},
            ]
        )
        logger.live_analysis._prune_locked(3.0)

    assert [row["sample_id"] for row in logger.live_analysis._samples] == [
        "edge",
        "recent-a",
        "recent-b",
    ]


def test_live_samples_prune_drops_malformed_rows(make_logger) -> None:
    logger = make_logger()

    with logger.live_analysis._lock:
        logger.live_analysis._samples.extend(
            [
                {"sample_id": "broken"},
                {"t_s": 2.2, "sample_id": "valid"},
            ]
        )
        logger.live_analysis._prune_locked(2.2)

    assert [row["sample_id"] for row in logger.live_analysis._samples] == ["valid"]


def test_post_analysis_uses_run_language_from_metadata(
    make_logger, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    history_db = HistoryDB(tmp_path / "history.db")
    logger = make_logger(history_db=history_db, language_provider=lambda: "nl")

    logger.start_logging()
    snapshot = logger._session_snapshot()
    assert snapshot is not None
    run_id, start_time_utc, start_mono, generation = snapshot
    logger._append_records(run_id, start_time_utc, start_mono, session_generation=generation)

    def _summary(metadata, samples, lang=None, file_name="run", include_samples=False):
        return {"lang": lang, "row_count": len(samples)}

    monkeypatch.setattr("vibesensor.analysis.summarize_run_data", _summary)
    logger.stop_logging()
    assert wait_until(lambda: history_db.get_run_status(run_id) == "complete", timeout_s=2.0)
    stored = history_db.get_run_analysis(run_id)
    assert stored is not None
    assert stored["lang"] == "nl"


def test_db_persists_when_jsonl_disabled(make_logger, tmp_path: Path) -> None:
    history_db = HistoryDB(tmp_path / "history.db")
    logger = make_logger(history_db=history_db, persist_history_db=True)

    logger.start_logging()
    snapshot = logger._session_snapshot()
    assert snapshot is not None
    run_id, start_time_utc, start_mono, generation = snapshot
    logger._append_records(run_id, start_time_utc, start_mono, session_generation=generation)
    logger.stop_logging()

    assert history_db.get_run(run_id) is not None
    assert history_db.get_run_samples(run_id)


def test_post_analysis_caps_sample_count_and_stores_sampling_metadata(
    make_logger, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Reduce the cap so we only need ~250 iterations instead of 13 000 (28 s -> <1 s).
    cap = 200
    monkeypatch.setattr("vibesensor.metrics_log.post_analysis._MAX_POST_ANALYSIS_SAMPLES", cap)

    history_db = HistoryDB(tmp_path / "history.db")
    logger = make_logger(history_db=history_db)

    logger.start_logging()
    snapshot = logger._session_snapshot()
    assert snapshot is not None
    run_id, start_time_utc, start_mono, generation = snapshot
    for _ in range(cap + 50):
        logger._append_records(run_id, start_time_utc, start_mono, session_generation=generation)

    def _summary(metadata, samples, lang=None, file_name="run", include_samples=False):
        return {"row_count": len(samples), "run_suitability": []}

    monkeypatch.setattr("vibesensor.analysis.summarize_run_data", _summary)
    logger.stop_logging()
    assert wait_until(lambda: history_db.get_run_status(run_id) == "complete", timeout_s=3.0)
    stored = history_db.get_run_analysis(run_id)
    assert stored is not None
    assert stored["row_count"] <= cap
    assert stored["analysis_metadata"]["total_sample_count"] >= stored["row_count"]
    assert stored["analysis_metadata"]["sampling_method"].startswith("stride_")
    suitability_checks = {str(item.get("check_key")) for item in stored.get("run_suitability", [])}
    assert "SUITABILITY_CHECK_ANALYSIS_SAMPLING" in suitability_checks


@pytest.mark.asyncio
async def test_run_offloads_append_records_with_to_thread(
    make_logger, fake_history_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    logger = make_logger(history_db=fake_history_db)

    logger.start_logging()
    captured: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):  # type: ignore[no-untyped-def]
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return False

    async def _cancel_sleep(_interval: float) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr("vibesensor.metrics_log.logger.asyncio.to_thread", _fake_to_thread)
    monkeypatch.setattr("vibesensor.metrics_log.logger.asyncio.sleep", _cancel_sleep)

    with pytest.raises(asyncio.CancelledError):
        await logger.run()

    assert captured.get("func") == logger._append_records
