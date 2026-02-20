from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from vibesensor.history_db import HistoryDB
from vibesensor.metrics_log import MetricsLogger

# -- MetricsLogger._safe_metric ------------------------------------------------


def test_safe_metric_valid() -> None:
    metrics = {"x": {"rms": 0.05, "p2p": 0.12}}
    result = MetricsLogger._safe_metric(metrics, "x", "rms")
    assert result == 0.05


def test_safe_metric_missing_axis() -> None:
    metrics = {"x": {"rms": 0.05}}
    assert MetricsLogger._safe_metric(metrics, "y", "rms") is None


def test_safe_metric_missing_key() -> None:
    metrics = {"x": {"rms": 0.05}}
    assert MetricsLogger._safe_metric(metrics, "x", "p2p") is None


def test_safe_metric_nan_returns_none() -> None:
    metrics = {"x": {"rms": float("nan")}}
    assert MetricsLogger._safe_metric(metrics, "x", "rms") is None


def test_safe_metric_inf_returns_none() -> None:
    metrics = {"x": {"rms": float("inf")}}
    assert MetricsLogger._safe_metric(metrics, "x", "rms") is None


def test_safe_metric_axis_not_dict_returns_none() -> None:
    metrics = {"x": "not_a_dict"}
    assert MetricsLogger._safe_metric(metrics, "x", "rms") is None


def test_safe_metric_non_numeric_returns_none() -> None:
    metrics = {"x": {"rms": "abc"}}
    assert MetricsLogger._safe_metric(metrics, "x", "rms") is None


@dataclass(slots=True)
class _FakeRecord:
    client_id: str
    name: str
    sample_rate_hz: int
    latest_metrics: dict
    frames_total: int = 0
    frames_dropped: int = 0
    queue_overflow_drops: int = 0


class _FakeRegistry:
    def __init__(self) -> None:
        self._records = {
            "active": _FakeRecord(
                client_id="active",
                name="front-left wheel",
                sample_rate_hz=800,
                latest_metrics={
                    "strength_metrics": {
                        "vibration_strength_db": 22.0,
                        "strength_bucket": "l2",
                        "top_peaks": [
                            {
                                "hz": 15.0,
                                "amp": 0.12,
                                "vibration_strength_db": 22.0,
                                "strength_bucket": "l2",
                            },
                        ],
                        "combined_spectrum_amp_g": [],
                    },
                    "combined": {
                        "peaks": [{"hz": 15.0, "amp": 0.12}],
                    },
                    "x": {"rms": 0.04, "p2p": 0.11, "peaks": [{"hz": 15.0, "amp": 0.12}]},
                    "y": {"rms": 0.03, "p2p": 0.10, "peaks": [{"hz": 16.0, "amp": 0.08}]},
                    "z": {"rms": 0.02, "p2p": 0.09, "peaks": [{"hz": 14.0, "amp": 0.07}]},
                },
            ),
            "stale": _FakeRecord(
                client_id="stale",
                name="rear-right wheel",
                sample_rate_hz=800,
                latest_metrics={
                    "strength_metrics": {
                        "vibration_strength_db": 28.0,
                        "strength_bucket": "l4",
                        "top_peaks": [
                            {
                                "hz": 28.0,
                                "amp": 0.26,
                                "vibration_strength_db": 28.0,
                                "strength_bucket": "l4",
                            },
                        ],
                        "combined_spectrum_amp_g": [],
                    },
                    "combined": {
                        "peaks": [{"hz": 28.0, "amp": 0.26}],
                    },
                    "x": {"rms": 0.10, "p2p": 0.22, "peaks": [{"hz": 28.0, "amp": 0.26}]},
                    "y": {"rms": 0.09, "p2p": 0.18, "peaks": [{"hz": 29.0, "amp": 0.20}]},
                    "z": {"rms": 0.08, "p2p": 0.17, "peaks": [{"hz": 27.0, "amp": 0.19}]},
                },
            ),
        }

    def active_client_ids(self) -> list[str]:
        return ["active"]

    def get(self, client_id: str) -> _FakeRecord | None:
        return self._records.get(client_id)


class _NoActiveRegistry(_FakeRegistry):
    def active_client_ids(self) -> list[str]:
        return []


class _FakeGPSMonitor:
    speed_mps = None
    effective_speed_mps = None
    override_speed_mps = None


class _FakeProcessor:
    def latest_sample_xyz(self, client_id: str):
        return (0.01, 0.02, 0.03)

    def latest_sample_rate_hz(self, client_id: str):
        return 800

    def clients_with_recent_data(self, client_ids: list[str], max_age_s: float = 3.0) -> list[str]:
        # In the fake, treat all provided clients as having recent data.
        return list(client_ids)


class _FakeAnalysisSettings:
    def snapshot(self) -> dict[str, float]:
        return {
            "tire_width_mm": 285.0,
            "tire_aspect_pct": 30.0,
            "rim_in": 21.0,
            "final_drive_ratio": 3.08,
            "current_gear_ratio": 0.64,
        }


class _FakeHistoryDB:
    def __init__(self) -> None:
        self.create_calls: list[tuple[str, str]] = []
        self.append_calls: list[tuple[str, int]] = []
        self.finalize_calls: list[str] = []

    def create_run(self, run_id: str, start_time_utc: str, metadata: dict) -> None:
        self.create_calls.append((run_id, start_time_utc))

    def append_samples(self, run_id: str, samples: list[dict]) -> None:
        self.append_calls.append((run_id, len(samples)))

    def finalize_run(self, run_id: str, end_time_utc: str) -> None:
        self.finalize_calls.append(run_id)


def _wait_until(predicate, timeout_s: float = 2.0, step_s: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step_s)
    return False


def test_build_sample_records_uses_only_active_clients(tmp_path: Path) -> None:
    logger = MetricsLogger(
        enabled=False,
        log_path=tmp_path / "metrics.jsonl",
        metrics_log_hz=2,
        registry=_FakeRegistry(),
        gps_monitor=_FakeGPSMonitor(),
        processor=_FakeProcessor(),
        analysis_settings=_FakeAnalysisSettings(),
        sensor_model="ADXL345",
        default_sample_rate_hz=800,
        fft_window_size_samples=1024,
    )

    rows = logger._build_sample_records(
        run_id="run-1",
        t_s=1.0,
        timestamp_utc="2026-02-16T12:00:00+00:00",
    )

    assert len(rows) == 1
    assert rows[0]["client_id"] == "active"
    assert rows[0]["client_name"] == "front-left wheel"


def test_speed_source_reports_override_when_override_set(tmp_path: Path) -> None:
    """speed_source should be 'override' when override_speed_mps is set."""
    gps = _FakeGPSMonitor()
    gps.speed_mps = 10.0  # GPS available
    gps.override_speed_mps = 20.0  # Override active
    gps.effective_speed_mps = 20.0  # Override takes priority

    logger = MetricsLogger(
        enabled=False,
        log_path=tmp_path / "metrics.jsonl",
        metrics_log_hz=2,
        registry=_FakeRegistry(),
        gps_monitor=gps,
        processor=_FakeProcessor(),
        analysis_settings=_FakeAnalysisSettings(),
        sensor_model="ADXL345",
        default_sample_rate_hz=800,
        fft_window_size_samples=1024,
    )

    rows = logger._build_sample_records(
        run_id="run-1",
        t_s=1.0,
        timestamp_utc="2026-02-16T12:00:00+00:00",
    )

    assert len(rows) == 1
    assert rows[0]["speed_source"] == "override"
    assert rows[0]["speed_kmh"] == pytest.approx(20.0 * 3.6, abs=0.01)


def test_speed_source_reports_gps_when_no_override(tmp_path: Path) -> None:
    """speed_source should be 'gps' when GPS is available and no override."""
    gps = _FakeGPSMonitor()
    gps.speed_mps = 10.0
    gps.override_speed_mps = None
    gps.effective_speed_mps = 10.0

    logger = MetricsLogger(
        enabled=False,
        log_path=tmp_path / "metrics.jsonl",
        metrics_log_hz=2,
        registry=_FakeRegistry(),
        gps_monitor=gps,
        processor=_FakeProcessor(),
        analysis_settings=_FakeAnalysisSettings(),
        sensor_model="ADXL345",
        default_sample_rate_hz=800,
        fft_window_size_samples=1024,
    )

    rows = logger._build_sample_records(
        run_id="run-1",
        t_s=1.0,
        timestamp_utc="2026-02-16T12:00:00+00:00",
    )

    assert len(rows) == 1
    assert rows[0]["speed_source"] == "gps"
    assert rows[0]["speed_kmh"] == pytest.approx(10.0 * 3.6, abs=0.01)


def test_speed_source_reports_missing_when_nothing_set(tmp_path: Path) -> None:
    """speed_source should be 'missing' when neither GPS nor override is set."""
    logger = MetricsLogger(
        enabled=False,
        log_path=tmp_path / "metrics.jsonl",
        metrics_log_hz=2,
        registry=_FakeRegistry(),
        gps_monitor=_FakeGPSMonitor(),
        processor=_FakeProcessor(),
        analysis_settings=_FakeAnalysisSettings(),
        sensor_model="ADXL345",
        default_sample_rate_hz=800,
        fft_window_size_samples=1024,
    )

    rows = logger._build_sample_records(
        run_id="run-1",
        t_s=1.0,
        timestamp_utc="2026-02-16T12:00:00+00:00",
    )

    assert len(rows) == 1
    assert rows[0]["speed_source"] == "missing"
    assert rows[0]["speed_kmh"] is None


def test_stop_without_samples_does_not_persist_history_run(tmp_path: Path) -> None:
    history_db = _FakeHistoryDB()
    logger = MetricsLogger(
        enabled=False,
        log_path=tmp_path / "metrics.jsonl",
        metrics_log_hz=2,
        registry=_FakeRegistry(),
        gps_monitor=_FakeGPSMonitor(),
        processor=_FakeProcessor(),
        analysis_settings=_FakeAnalysisSettings(),
        sensor_model="ADXL345",
        default_sample_rate_hz=800,
        fft_window_size_samples=1024,
        history_db=history_db,
    )

    logger.start_logging()
    logger.stop_logging()

    assert history_db.create_calls == []
    assert history_db.append_calls == []
    assert history_db.finalize_calls == []


def test_history_run_created_on_first_sample_append(tmp_path: Path) -> None:
    history_db = _FakeHistoryDB()
    logger = MetricsLogger(
        enabled=False,
        log_path=tmp_path / "metrics.jsonl",
        metrics_log_hz=2,
        registry=_FakeRegistry(),
        gps_monitor=_FakeGPSMonitor(),
        processor=_FakeProcessor(),
        analysis_settings=_FakeAnalysisSettings(),
        sensor_model="ADXL345",
        default_sample_rate_hz=800,
        fft_window_size_samples=1024,
        history_db=history_db,
    )

    logger.start_logging()
    snapshot = logger._session_snapshot()
    assert snapshot is not None
    run_id, start_time_utc, start_mono = snapshot

    timed_out = logger._append_records(run_id, start_time_utc, start_mono)

    assert timed_out is False
    assert history_db.create_calls == [(run_id, start_time_utc)]
    assert history_db.append_calls == [(run_id, 1)]


def test_append_records_reports_timeout_when_no_data_for_threshold(tmp_path: Path) -> None:
    logger = MetricsLogger(
        enabled=False,
        log_path=tmp_path / "metrics.jsonl",
        metrics_log_hz=2,
        registry=_NoActiveRegistry(),
        gps_monitor=_FakeGPSMonitor(),
        processor=_FakeProcessor(),
        analysis_settings=_FakeAnalysisSettings(),
        sensor_model="ADXL345",
        default_sample_rate_hz=800,
        fft_window_size_samples=1024,
    )

    logger.start_logging()
    snapshot = logger._session_snapshot()
    assert snapshot is not None
    run_id, start_time_utc, start_mono = snapshot
    logger._last_data_progress_mono_s = 0.0

    timed_out = logger._append_records(run_id, start_time_utc, start_mono)

    assert timed_out is True


def test_stop_logging_does_not_block_on_post_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stopping capture should be fast even when analysis is slow.

    Post-analysis belongs in background processing because users expect stop controls to respond
    promptly. This test simulates a slow summarizer and requires stop_logging to return quickly
    while analysis completes asynchronously afterward.
    """
    history_db = HistoryDB(tmp_path / "history.db")
    logger = MetricsLogger(
        enabled=False,
        log_path=tmp_path / "metrics.jsonl",
        metrics_log_hz=2,
        registry=_FakeRegistry(),
        gps_monitor=_FakeGPSMonitor(),
        processor=_FakeProcessor(),
        analysis_settings=_FakeAnalysisSettings(),
        sensor_model="ADXL345",
        default_sample_rate_hz=800,
        fft_window_size_samples=1024,
        history_db=history_db,
    )
    logger.start_logging()
    snapshot = logger._session_snapshot()
    assert snapshot is not None
    run_id, start_time_utc, start_mono = snapshot
    logger._append_records(run_id, start_time_utc, start_mono)

    def _slow_summary(*args, **kwargs):
        time.sleep(0.35)
        return {"summary": "ok"}

    monkeypatch.setattr("vibesensor.report_analysis.summarize_run_data", _slow_summary)
    started = time.monotonic()
    logger.stop_logging()
    elapsed = time.monotonic() - started

    assert elapsed < 0.15
    assert _wait_until(lambda: history_db.get_run_status(run_id) == "complete", timeout_s=3.0)


def test_post_analysis_failure_sets_persistent_error_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    history_db = HistoryDB(tmp_path / "history.db")
    logger = MetricsLogger(
        enabled=False,
        log_path=tmp_path / "metrics.jsonl",
        metrics_log_hz=2,
        registry=_FakeRegistry(),
        gps_monitor=_FakeGPSMonitor(),
        processor=_FakeProcessor(),
        analysis_settings=_FakeAnalysisSettings(),
        sensor_model="ADXL345",
        default_sample_rate_hz=800,
        fft_window_size_samples=1024,
        history_db=history_db,
    )
    logger.start_logging()
    snapshot = logger._session_snapshot()
    assert snapshot is not None
    run_id, start_time_utc, start_mono = snapshot
    logger._append_records(run_id, start_time_utc, start_mono)

    def _failing_summary(*args, **kwargs):
        raise RuntimeError("analysis exploded")

    monkeypatch.setattr("vibesensor.report_analysis.summarize_run_data", _failing_summary)
    logger.stop_logging()

    assert _wait_until(lambda: history_db.get_run_status(run_id) == "error", timeout_s=2.0)
    run = history_db.get_run(run_id)
    assert run is not None
    assert "analysis exploded" in str(run.get("error_message", ""))


def test_analysis_snapshot_isolated_per_logging_run(tmp_path: Path) -> None:
    logger = MetricsLogger(
        enabled=False,
        log_path=tmp_path / "metrics.jsonl",
        metrics_log_hz=2,
        registry=_FakeRegistry(),
        gps_monitor=_FakeGPSMonitor(),
        processor=_FakeProcessor(),
        analysis_settings=_FakeAnalysisSettings(),
        sensor_model="ADXL345",
        default_sample_rate_hz=800,
        fft_window_size_samples=1024,
    )

    logger.start_logging()
    logger._live_samples.append({"run_marker": "run1"})
    logger.stop_logging()

    logger.start_logging()
    metadata, samples = logger.analysis_snapshot()

    assert metadata["run_id"] != "live"
    assert all(sample.get("run_marker") != "run1" for sample in samples)


def test_post_analysis_uses_run_language_from_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    history_db = HistoryDB(tmp_path / "history.db")
    logger = MetricsLogger(
        enabled=False,
        log_path=tmp_path / "metrics.jsonl",
        metrics_log_hz=2,
        registry=_FakeRegistry(),
        gps_monitor=_FakeGPSMonitor(),
        processor=_FakeProcessor(),
        analysis_settings=_FakeAnalysisSettings(),
        sensor_model="ADXL345",
        default_sample_rate_hz=800,
        fft_window_size_samples=1024,
        history_db=history_db,
        language_provider=lambda: "nl",
    )
    logger.start_logging()
    snapshot = logger._session_snapshot()
    assert snapshot is not None
    run_id, start_time_utc, start_mono = snapshot
    logger._append_records(run_id, start_time_utc, start_mono)

    def _summary(metadata, samples, lang=None, file_name="run", include_samples=False):
        return {"lang": lang, "row_count": len(samples)}

    monkeypatch.setattr("vibesensor.report_analysis.summarize_run_data", _summary)
    logger.stop_logging()
    assert _wait_until(lambda: history_db.get_run_status(run_id) == "complete", timeout_s=2.0)
    stored = history_db.get_run_analysis(run_id)
    assert stored is not None
    assert stored["lang"] == "nl"


def test_db_persists_when_jsonl_disabled(tmp_path: Path) -> None:
    history_db = HistoryDB(tmp_path / "history.db")
    logger = MetricsLogger(
        enabled=False,
        log_path=tmp_path / "metrics.jsonl",
        metrics_log_hz=2,
        registry=_FakeRegistry(),
        gps_monitor=_FakeGPSMonitor(),
        processor=_FakeProcessor(),
        analysis_settings=_FakeAnalysisSettings(),
        sensor_model="ADXL345",
        default_sample_rate_hz=800,
        fft_window_size_samples=1024,
        history_db=history_db,
        persist_history_db=True,
    )
    logger.start_logging()
    snapshot = logger._session_snapshot()
    assert snapshot is not None
    run_id, start_time_utc, start_mono = snapshot
    logger._append_records(run_id, start_time_utc, start_mono)
    logger.stop_logging()

    assert history_db.get_run(run_id) is not None
    assert history_db.get_run_samples(run_id)


def test_post_analysis_caps_sample_count_and_stores_sampling_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    history_db = HistoryDB(tmp_path / "history.db")
    logger = MetricsLogger(
        enabled=False,
        log_path=tmp_path / "metrics.jsonl",
        metrics_log_hz=2,
        registry=_FakeRegistry(),
        gps_monitor=_FakeGPSMonitor(),
        processor=_FakeProcessor(),
        analysis_settings=_FakeAnalysisSettings(),
        sensor_model="ADXL345",
        default_sample_rate_hz=800,
        fft_window_size_samples=1024,
        history_db=history_db,
    )
    logger.start_logging()
    snapshot = logger._session_snapshot()
    assert snapshot is not None
    run_id, start_time_utc, start_mono = snapshot
    for _ in range(13_000):
        logger._append_records(run_id, start_time_utc, start_mono)

    def _summary(metadata, samples, lang=None, file_name="run", include_samples=False):
        return {"row_count": len(samples)}

    monkeypatch.setattr("vibesensor.report_analysis.summarize_run_data", _summary)
    logger.stop_logging()
    assert _wait_until(lambda: history_db.get_run_status(run_id) == "complete", timeout_s=3.0)
    stored = history_db.get_run_analysis(run_id)
    assert stored is not None
    assert stored["row_count"] <= 12_000
    assert stored["analysis_metadata"]["total_sample_count"] >= stored["row_count"]
