"""Integration test for MetricsLogger full lifecycle with a real HistoryDB."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from vibesensor.history_db import HistoryDB
from vibesensor.metrics_log import MetricsLogger

# -- Minimal fakes (same shape as test_metrics_log_helpers.py) -----------------


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
        }

    def active_client_ids(self) -> list[str]:
        return ["active"]

    def get(self, client_id: str) -> _FakeRecord | None:
        return self._records.get(client_id)


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


def _wait_until(predicate, timeout_s: float = 2.0, step_s: float = 0.02) -> bool:
    from conftest import wait_until

    return wait_until(predicate, timeout_s=timeout_s, step_s=step_s)


# -- Test ----------------------------------------------------------------------


def test_start_append_stop_produces_complete_run_in_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full lifecycle: start → append → stop → analyze → complete with a real DB."""
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

    fake_analysis = {"score": 42, "details": "looks good"}

    def _fast_summary(metadata, samples, lang=None, file_name="run", include_samples=False):
        return dict(fake_analysis)

    monkeypatch.setattr("vibesensor.report_analysis.summarize_run_data", _fast_summary)
    logger.stop_logging()

    assert _wait_until(lambda: history_db.get_run_status(run_id) == "complete", timeout_s=3.0)

    stored = history_db.get_run_analysis(run_id)
    assert stored is not None
    assert stored["score"] == 42
    assert stored["details"] == "looks good"
    assert "analysis_metadata" in stored
