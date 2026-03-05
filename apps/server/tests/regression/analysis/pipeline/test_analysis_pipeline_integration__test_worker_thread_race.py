"""Analysis pipeline integration regressions.

Each test is tagged with the fix number it validates.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from vibesensor.analysis import summarize_run_data
from vibesensor.history_db import HistoryDB
from vibesensor.metrics_log import MetricsLogger

_START = "2026-01-01T00:00:00Z"

_END = "2026-01-01T00:05:00Z"


@pytest.fixture()
def db(tmp_path: Path) -> HistoryDB:
    return HistoryDB(tmp_path / "pipeline_test.db")


def _simple_metadata(run_id: str = "test-run", lang: str = "en") -> dict[str, Any]:
    return {
        "run_id": run_id,
        "start_time_utc": _START,
        "end_time_utc": _END,
        "sensor_model": "ADXL345",
        "language": lang,
    }


def _simple_samples(n: int = 20) -> list[dict[str, Any]]:
    return [
        {
            "t_s": float(i),
            "speed_kmh": 60.0 + i,
            "vibration_strength_db": 25.0 + i * 0.5,
            "accel_x_g": 0.01 * i,
            "accel_y_g": 0.02 * i,
            "accel_z_g": 1.0 + 0.005 * i,
            "client_id": "sensor_a",
            "location": "Front Left",
        }
        for i in range(n)
    ]


def _summarize(**overrides: Any) -> dict[str, Any]:
    """Shortcut: summarize_run_data with sensible defaults."""
    kw: dict[str, Any] = {"include_samples": False}
    kw.update(overrides)
    meta = kw.pop("metadata", _simple_metadata())
    samples = kw.pop("samples", _simple_samples())
    return summarize_run_data(meta, samples, **kw)


def _setup_stale_pair(db: HistoryDB) -> None:
    """Shared setup: r1 finalized (analyzing), r2 still recording."""
    db.create_run("r1", _START, {})
    db.finalize_run("r1", _END)
    db.create_run("r2", "2026-01-01T00:10:00Z", {})


class TestWorkerThreadRace:
    """Fix 5: _analysis_thread cleared on exit so new scheduling works."""

    def test_analysis_thread_cleared_on_completion(self, tmp_path: Path) -> None:
        class FakeReg:
            def active_client_ids(self):
                return []

            def get(self, _):
                return None

        class FakeGPS:
            speed_mps = None
            effective_speed_mps = None
            override_speed_mps = None

        class FakeProc:
            pass

        class FakeSettings:
            def snapshot(self):
                return {}

        logger = MetricsLogger(
            enabled=False,
            log_path=tmp_path / "m.jsonl",
            metrics_log_hz=2,
            registry=FakeReg(),
            gps_monitor=FakeGPS(),
            processor=FakeProc(),
            analysis_settings=FakeSettings(),
            sensor_model="test",
            default_sample_rate_hz=800,
            fft_window_size_samples=256,
        )

        seen: list[str] = []

        def _mock_analysis(run_id: str) -> None:
            seen.append(run_id)

        logger._post_analysis._run_post_analysis = _mock_analysis  # type: ignore[assignment]
        logger._schedule_post_analysis("run-1")
        logger.wait_for_post_analysis(timeout_s=2.0)

        with logger._post_analysis._lock:
            assert logger._post_analysis._analysis_thread is None

        logger._schedule_post_analysis("run-2")
        logger.wait_for_post_analysis(timeout_s=2.0)
        assert seen == ["run-1", "run-2"]
