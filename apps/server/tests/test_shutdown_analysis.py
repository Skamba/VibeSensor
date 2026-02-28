"""Tests for #302: ensure analysis completes before DB close on shutdown."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
import yaml

from vibesensor.metrics_log import MetricsLogger

# ---------------------------------------------------------------------------
# Minimal fakes (same style as test_metrics_log_helpers.py)
# ---------------------------------------------------------------------------


class _FakeRecord:
    client_id: str = "c1"
    name: str = "test"
    sample_rate_hz: int = 800
    latest_metrics: dict  # type: ignore[assignment]
    location: str = ""
    frames_total: int = 0
    frames_dropped: int = 0
    queue_overflow_drops: int = 0

    def __init__(self) -> None:
        self.latest_metrics = {}


class _FakeRegistry:
    def active_client_ids(self) -> list[str]:
        return []

    def get(self, client_id: str):
        return None


class _FakeGPSMonitor:
    speed_mps = None
    effective_speed_mps = None
    override_speed_mps = None


class _FakeProcessor:
    def latest_sample_xyz(self, client_id: str):
        return (0.0, 0.0, 0.0)

    def latest_sample_rate_hz(self, client_id: str):
        return 800

    def clients_with_recent_data(self, client_ids, max_age_s=3.0):
        return list(client_ids)


class _FakeAnalysisSettings:
    def snapshot(self) -> dict:
        return {}


def _make_logger(tmp_path: Path, history_db=None) -> MetricsLogger:
    return MetricsLogger(
        enabled=False,
        log_path=tmp_path / "m.jsonl",
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


# ---------------------------------------------------------------------------
# wait_for_post_analysis return value tests
# ---------------------------------------------------------------------------


def test_wait_returns_true_when_no_work(tmp_path: Path) -> None:
    """No queued analysis → should return True immediately."""
    logger = _make_logger(tmp_path)
    assert logger.wait_for_post_analysis(timeout_s=0.5) is True


def test_wait_returns_true_when_analysis_finishes(tmp_path: Path, monkeypatch) -> None:
    """Analysis finishes within timeout → returns True."""
    logger = _make_logger(tmp_path, history_db=object())
    completed: list[str] = []

    def _slow_analysis(run_id: str) -> None:
        time.sleep(0.1)
        completed.append(run_id)

    monkeypatch.setattr(logger, "_run_post_analysis", _slow_analysis)
    logger._schedule_post_analysis("run-a")

    result = logger.wait_for_post_analysis(timeout_s=5.0)
    assert result is True
    assert completed == ["run-a"]


def test_wait_returns_false_on_timeout(tmp_path: Path, monkeypatch) -> None:
    """Analysis does NOT finish within timeout → returns False."""
    logger = _make_logger(tmp_path, history_db=object())
    started = threading.Event()

    def _very_slow_analysis(run_id: str) -> None:
        started.set()
        time.sleep(1.0)  # Just needs to outlive the 0.3s wait timeout

    monkeypatch.setattr(logger, "_run_post_analysis", _very_slow_analysis)
    logger._schedule_post_analysis("run-slow")

    # Wait until the analysis thread has actually started
    started.wait(timeout=2.0)

    result = logger.wait_for_post_analysis(timeout_s=0.3)
    assert result is False


# ---------------------------------------------------------------------------
# Shutdown ordering: DB must not close before analysis finishes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shutdown_waits_for_analysis_before_db_close(tmp_path: Path, monkeypatch) -> None:
    """Integration: stop_runtime waits for analysis, then closes DB — not before."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "logging": {
                    "log_metrics": False,
                    "metrics_log_path": str(tmp_path / "metrics.jsonl"),
                    "history_db_path": str(tmp_path / "history.db"),
                    "shutdown_analysis_timeout_s": 10,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("VIBESENSOR_SERVE_STATIC", "0")
    monkeypatch.setenv("VIBESENSOR_DISABLE_AUTO_APP", "1")

    from vibesensor import app as app_module

    async def _fake_udp_receiver(*args, **kwargs):
        return None, None

    async def _fake_start(self):
        return None

    events: list[str] = []

    original_close = app_module.HistoryDB.close

    def _tracking_close(self):
        events.append("db_close")
        original_close(self)

    original_wait = MetricsLogger.wait_for_post_analysis

    def _tracking_wait(self, timeout_s=30.0):
        result = original_wait(self, timeout_s)
        events.append("analysis_wait_done")
        return result

    monkeypatch.setattr(app_module, "start_udp_data_receiver", _fake_udp_receiver)
    monkeypatch.setattr(app_module.UDPControlPlane, "start", _fake_start)
    monkeypatch.setattr(app_module.HistoryDB, "close", _tracking_close)
    monkeypatch.setattr(MetricsLogger, "wait_for_post_analysis", _tracking_wait)

    app = app_module.create_app(config_path=cfg_path)
    async with app.router.lifespan_context(app):
        pass

    # The key assertion: analysis_wait_done must appear BEFORE db_close
    assert "analysis_wait_done" in events
    assert "db_close" in events
    assert events.index("analysis_wait_done") < events.index("db_close")


# ---------------------------------------------------------------------------
# Config: shutdown_analysis_timeout_s
# ---------------------------------------------------------------------------


def test_config_shutdown_analysis_timeout_default(tmp_path: Path) -> None:
    """Default shutdown_analysis_timeout_s should be 30."""
    from vibesensor.config import load_config

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "logging": {
                    "metrics_log_path": str(tmp_path / "m.jsonl"),
                },
            }
        ),
        encoding="utf-8",
    )
    config = load_config(cfg_path)
    assert config.logging.shutdown_analysis_timeout_s == 30.0


def test_config_shutdown_analysis_timeout_custom(tmp_path: Path) -> None:
    """Custom shutdown_analysis_timeout_s should be respected."""
    from vibesensor.config import load_config

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "logging": {
                    "metrics_log_path": str(tmp_path / "m.jsonl"),
                    "shutdown_analysis_timeout_s": 60,
                },
            }
        ),
        encoding="utf-8",
    )
    config = load_config(cfg_path)
    assert config.logging.shutdown_analysis_timeout_s == 60.0
