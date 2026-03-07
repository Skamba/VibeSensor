"""Tests for vibesensor.runtime – RuntimeState lifecycle and processing loop.

These tests verify the newly extracted RuntimeState methods that were
previously nested closures inside create_app() and therefore untestable
in isolation.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("VIBESENSOR_DISABLE_AUTO_APP", "1")


# ---------------------------------------------------------------------------
# Stubs – lightweight stand-ins for RuntimeState dependencies
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _StubProcessingConfig:
    fft_update_hz: int = 10
    sample_rate_hz: int = 800
    fft_n: int = 2048
    ui_push_hz: int = 10
    ui_heavy_push_hz: int = 4
    waveform_seconds: int = 8
    waveform_display_hz: int = 120
    spectrum_max_hz: int = 200
    client_ttl_seconds: int = 120
    accel_scale_g_per_lsb: float | None = None
    spectrum_min_hz: int = 5


@dataclass(slots=True)
class _StubUDPConfig:
    data_host: str = "0.0.0.0"
    data_port: int = 5005
    data_queue_maxsize: int = 100
    control_host: str = "0.0.0.0"
    control_port: int = 5006


@dataclass(slots=True)
class _StubLoggingConfig:
    shutdown_analysis_timeout_s: float = 5.0
    log_metrics: bool = False
    metrics_log_path: str = "/tmp/m.jsonl"
    history_db_path: str = ":memory:"
    metrics_log_hz: int = 1
    no_data_timeout_s: int = 10
    sensor_model: str = "test"
    persist_history_db: bool = False


@dataclass(slots=True)
class _StubGpsConfig:
    gpsd_host: str = "127.0.0.1"
    gpsd_port: int = 2947


@dataclass(slots=True)
class _StubConfig:
    processing: _StubProcessingConfig
    udp: _StubUDPConfig = None  # type: ignore[assignment]
    logging: _StubLoggingConfig = None  # type: ignore[assignment]
    gps: _StubGpsConfig = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.udp is None:
            self.udp = _StubUDPConfig()
        if self.logging is None:
            self.logging = _StubLoggingConfig()
        if self.gps is None:
            self.gps = _StubGpsConfig()


class _StubRecord:
    sample_rate_hz: int = 800
    frame_samples: int = 1024


class _StubRegistry:
    def __init__(self) -> None:
        self._clients: dict[str, _StubRecord] = {}

    def evict_stale(self) -> None:
        pass

    def active_client_ids(self) -> list[str]:
        return list(self._clients.keys())

    def get(self, client_id: str) -> _StubRecord | None:
        return self._clients.get(client_id)

    def set_latest_metrics(self, client_id: str, metrics: Any) -> None:
        pass


class _StubProcessor:
    def __init__(self) -> None:
        self.compute_all_calls = 0

    def clients_with_recent_data(self, client_ids: list[str], max_age_s: float = 3.0) -> list[str]:
        return list(client_ids)

    def compute_all(
        self, client_ids: list[str], sample_rates_hz: dict[str, int] | None = None
    ) -> dict[str, Any]:
        self.compute_all_calls += 1
        return {}

    def evict_clients(self, active: set[str]) -> None:
        pass


def _make_runtime(**overrides: Any):
    """Build a RuntimeState with stubs for lifecycle testing."""
    from vibesensor.runtime import RuntimeState

    defaults: dict[str, Any] = {
        "config": _StubConfig(processing=_StubProcessingConfig()),
        "registry": _StubRegistry(),
        "processor": _StubProcessor(),
        "control_plane": MagicMock(),
        "ws_hub": MagicMock(),
        "gps_monitor": MagicMock(),
        "analysis_settings": MagicMock(),
        "metrics_logger": MagicMock(),
        "live_diagnostics": MagicMock(),
        "settings_store": MagicMock(),
        "history_db": MagicMock(),
        "update_manager": MagicMock(),
        "esp_flash_manager": MagicMock(),
        "worker_pool": MagicMock(),
    }
    defaults.update(overrides)
    return RuntimeState(**defaults)


# ---------------------------------------------------------------------------
# processing_loop helpers & tests
# ---------------------------------------------------------------------------


async def _run_processing_loop(rt, *, max_ticks: int = 1) -> None:
    """Run *rt*.processing_loop() for *max_ticks* iterations, then cancel.

    Temporarily replaces ``asyncio.sleep`` with a counting stub so the loop
    completes deterministically without real delays.
    """
    tick_count = 0
    original_sleep = asyncio.sleep

    async def _counting_sleep(delay: float) -> None:
        nonlocal tick_count
        tick_count += 1
        if tick_count >= max_ticks:
            raise asyncio.CancelledError
        await original_sleep(0)

    asyncio.sleep = _counting_sleep
    try:
        with pytest.raises(asyncio.CancelledError):
            await rt.processing_loop()
    finally:
        asyncio.sleep = original_sleep


@pytest.mark.asyncio
async def test_processing_loop_runs_one_tick_and_resets_state() -> None:
    """processing_loop should call compute_all and set state to 'ok'."""
    rt = _make_runtime()
    rt.processing_state = "degraded"

    await _run_processing_loop(rt, max_ticks=1)

    assert rt.processing_state == "ok"


@pytest.mark.asyncio
async def test_processing_loop_handles_failure_gracefully() -> None:
    """When compute_all raises, processing_loop should increment failure count."""
    processor = _StubProcessor()

    def _failing_compute(*args, **kwargs):
        raise RuntimeError("test failure")

    processor.compute_all = _failing_compute
    rt = _make_runtime(processor=processor)

    await _run_processing_loop(rt, max_ticks=1)

    assert rt.processing_failure_count >= 1
    assert rt.processing_state in ("degraded", "fatal")


@pytest.mark.asyncio
async def test_processing_loop_broadcasts_sync_clock() -> None:
    """processing_loop should periodically call broadcast_sync_clock."""
    control_plane = MagicMock()
    # fft_update_hz=1 → interval=1.0 → sync every ~5 ticks
    rt = _make_runtime(
        config=_StubConfig(
            processing=_StubProcessingConfig(fft_update_hz=1),
        ),
        control_plane=control_plane,
    )

    await _run_processing_loop(rt, max_ticks=6)

    assert control_plane.broadcast_sync_clock.called


# ---------------------------------------------------------------------------
# start / stop tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_creates_tasks(monkeypatch) -> None:
    """RuntimeState.start() should populate the tasks list."""
    from vibesensor import runtime as runtime_mod

    async def _fake_udp(*args, **kwargs):
        return None, None

    monkeypatch.setattr(runtime_mod, "start_udp_data_receiver", _fake_udp)

    control_plane = MagicMock()
    control_plane.start = AsyncMock()
    ws_hub = MagicMock()
    ws_hub.run = AsyncMock(side_effect=asyncio.CancelledError)
    metrics_logger = MagicMock()
    metrics_logger.run = AsyncMock(side_effect=asyncio.CancelledError)
    gps_monitor = MagicMock()
    gps_monitor.run = AsyncMock(side_effect=asyncio.CancelledError)
    update_manager = MagicMock()
    update_manager.startup_recover = AsyncMock()

    rt = _make_runtime(
        control_plane=control_plane,
        ws_hub=ws_hub,
        metrics_logger=metrics_logger,
        gps_monitor=gps_monitor,
        update_manager=update_manager,
    )

    await rt.start()
    assert len(rt.tasks) == 5
    assert control_plane.start.called

    # Cleanup
    for task in rt.tasks:
        task.cancel()
    await asyncio.gather(*rt.tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_stop_cancels_tasks_and_closes_resources(monkeypatch) -> None:
    """RuntimeState.stop() should cancel tasks, close DB and worker pool."""
    from vibesensor import runtime as runtime_mod

    async def _fake_udp(*args, **kwargs):
        return MagicMock(), None

    monkeypatch.setattr(runtime_mod, "start_udp_data_receiver", _fake_udp)

    metrics_logger = MagicMock()
    metrics_logger.stop_logging = MagicMock()
    metrics_logger.wait_for_post_analysis = MagicMock(return_value=True)

    history_db = MagicMock()
    worker_pool = MagicMock()
    control_plane = MagicMock()
    control_plane.start = AsyncMock()
    control_plane.close = MagicMock()
    update_manager = MagicMock()
    update_manager._task = None
    esp_flash_manager = MagicMock()
    esp_flash_manager._task = None

    ws_hub = MagicMock()
    ws_hub.run = AsyncMock(side_effect=asyncio.CancelledError)
    gps_monitor = MagicMock()
    gps_monitor.run = AsyncMock(side_effect=asyncio.CancelledError)
    metrics_logger.run = AsyncMock(side_effect=asyncio.CancelledError)
    update_manager.startup_recover = AsyncMock()

    rt = _make_runtime(
        control_plane=control_plane,
        ws_hub=ws_hub,
        metrics_logger=metrics_logger,
        gps_monitor=gps_monitor,
        update_manager=update_manager,
        esp_flash_manager=esp_flash_manager,
        history_db=history_db,
        worker_pool=worker_pool,
    )

    await rt.start()
    assert len(rt.tasks) > 0

    await rt.stop()
    assert rt.tasks == []
    assert metrics_logger.stop_logging.called
    assert worker_pool.shutdown.called
    assert history_db.close.called


@pytest.mark.parametrize("attr", ["processing_loop", "start", "stop", "build_ws_payload"])
def test_runtime_state_has_public_method(attr: str) -> None:
    """Canonical import path should expose key public methods."""
    from vibesensor.runtime import RuntimeState

    assert hasattr(RuntimeState, attr), f"RuntimeState missing {attr}"
