"""Tests for vibesensor.infra.runtime – RuntimeState lifecycle and processing loop.

These tests verify the newly extracted RuntimeState methods that were
previously nested closures inside create_app() and therefore untestable
in isolation.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, get_type_hints
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
    client_live_ttl_seconds: int = 10
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
    history_db_path: str = ":memory:"
    metrics_log_hz: int = 1
    no_data_timeout_s: int = 10
    persist_history_db: bool = False


@dataclass(slots=True)
class _StubGpsConfig:
    gps_enabled: bool = True
    gpsd_host: str = "127.0.0.1"
    gpsd_port: int = 2947


@dataclass(slots=True)
class _StubConfig:
    processing: _StubProcessingConfig
    udp: _StubUDPConfig = None
    logging: _StubLoggingConfig = None
    gps: _StubGpsConfig = None

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


class _StubProcessor:
    def __init__(self) -> None:
        self.compute_all_calls = 0

    def clients_with_recent_data(self, client_ids: list[str], max_age_s: float = 3.0) -> list[str]:
        return list(client_ids)

    def compute_all(
        self,
        client_ids: list[str],
        sample_rates_hz: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        self.compute_all_calls += 1
        return {}

    def evict_clients(self, active: set[str]) -> None:
        pass


def _make_runtime(**overrides: Any):
    """Build a RuntimeState with stubs for lifecycle testing."""
    import vibesensor.infra.runtime as runtime_module
    from vibesensor.app.runtime_state import RuntimeState
    from vibesensor.infra.runtime.lifecycle import LifecycleManager, LifecycleRuntime
    from vibesensor.infra.runtime.processing_loop import (
        ProcessingLoop,
        ProcessingLoopState,
    )
    from vibesensor.infra.runtime.ws_broadcast import (
        WsBroadcastService,
    )

    config = overrides.pop("config", _StubConfig(processing=_StubProcessingConfig()))
    registry = overrides.pop("registry", _StubRegistry())
    processor = overrides.pop("processor", _StubProcessor())
    control_plane = overrides.pop("control_plane", MagicMock())
    worker_pool = overrides.pop("worker_pool", MagicMock())
    settings_store = overrides.pop("settings_store", MagicMock())
    gps_monitor = overrides.pop("gps_monitor", MagicMock())
    history_db = overrides.pop("history_db", MagicMock())
    diagnostics = overrides.pop("run_recorder", MagicMock())
    update_manager = overrides.pop("update_manager", MagicMock())
    esp_flash_manager = overrides.pop("esp_flash_manager", MagicMock())
    processing_state = ProcessingLoopState()
    health_state = runtime_module.RuntimeHealthState()
    rt = RuntimeState(
        config=config,
        registry=registry,
        processor=processor,
        control_plane=control_plane,
        worker_pool=worker_pool,
        settings_store=settings_store,
        gps_monitor=gps_monitor,
        history_db=history_db,
        processing_loop_state=processing_state,
        health_state=health_state,
        processing_loop=ProcessingLoop(
            state=processing_state,
            fft_update_hz=config.processing.fft_update_hz,
            sample_rate_hz=config.processing.sample_rate_hz,
            fft_n=config.processing.fft_n,
            registry=registry,
            processor=processor,
            control_plane=control_plane,
        ),
        ws_hub=overrides.pop("ws_hub", MagicMock()),
        ws_broadcast=WsBroadcastService(
            ui_push_hz=config.processing.ui_push_hz,
            ui_heavy_push_hz=config.processing.ui_heavy_push_hz,
            registry=registry,
            processor=processor,
            gps_monitor=gps_monitor,
            gps_enabled=config.gps.gps_enabled,
            settings_reader=settings_store,
            speed_source_reader=settings_store,
        ),
        run_recorder=diagnostics,
        update_manager=update_manager,
        esp_flash_manager=esp_flash_manager,
    )
    lifecycle_runtime = LifecycleRuntime(
        health_state=health_state,
        history_db_path=config.logging.history_db_path,
        udp_data_host=config.udp.data_host,
        udp_data_port=config.udp.data_port,
        udp_data_queue_maxsize=config.udp.data_queue_maxsize,
        gpsd_host=config.gps.gpsd_host,
        gpsd_port=config.gps.gpsd_port,
        shutdown_analysis_timeout_s=config.logging.shutdown_analysis_timeout_s,
        registry=registry,
        processor=processor,
        control_plane=control_plane,
        processing_loop=rt.processing_loop,
        ws_hub=rt.ws_hub,
        ws_broadcast=rt.ws_broadcast,
        run_recorder=diagnostics,
        gps_monitor=gps_monitor,
        update_manager=update_manager,
        esp_flash_manager=esp_flash_manager,
        worker_pool=worker_pool,
        history_db=history_db,
    )
    lifecycle = LifecycleManager(runtime=lifecycle_runtime, start_udp_receiver=AsyncMock())
    if overrides:
        for name, value in overrides.items():
            setattr(rt, name, value)
    return rt, lifecycle


# ---------------------------------------------------------------------------
# processing_loop helpers & tests
# ---------------------------------------------------------------------------


async def _run_processing_loop(rt, *, max_ticks: int = 1) -> None:
    """Run *rt*.processing_loop.run() for *max_ticks* iterations, then cancel.

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

    with patch("asyncio.sleep", _counting_sleep):
        with pytest.raises(asyncio.CancelledError):
            await rt.processing_loop.run()


@pytest.mark.asyncio
async def test_processing_loop_runs_one_tick_and_resets_state() -> None:
    """processing_loop should call compute_all and set state to 'ok'."""
    rt, _ = _make_runtime()
    rt.processing_loop_state.processing_state = "degraded"

    await _run_processing_loop(rt, max_ticks=1)

    assert rt.processing_loop_state.processing_state == "ok"


@pytest.mark.asyncio
async def test_processing_loop_handles_failure_gracefully() -> None:
    """When compute_all raises, processing_loop should increment failure count."""
    processor = _StubProcessor()

    def _failing_compute(*args, **kwargs):
        raise RuntimeError("test failure")

    processor.compute_all = _failing_compute
    rt, _ = _make_runtime(processor=processor)

    await _run_processing_loop(rt, max_ticks=1)

    assert rt.processing_loop_state.processing_failure_count >= 1
    assert rt.processing_loop_state.processing_state in ("degraded", "fatal")


@pytest.mark.asyncio
async def test_processing_loop_broadcasts_sync_clock() -> None:
    """processing_loop should periodically call broadcast_sync_clock."""
    control_plane = MagicMock()
    # fft_update_hz=1 → interval=1.0 → sync every ~5 ticks
    rt, _ = _make_runtime(
        config=_StubConfig(
            processing=_StubProcessingConfig(fft_update_hz=1),
        ),
        control_plane=control_plane,
    )

    await _run_processing_loop(rt, max_ticks=6)

    control_plane.broadcast_sync_clock.assert_called_once()


# ---------------------------------------------------------------------------
# start / stop tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_creates_tasks(monkeypatch) -> None:
    """LifecycleManager.start() should populate the tasks list."""

    async def _fake_udp(*args, **kwargs):
        return None, None

    control_plane = MagicMock()
    control_plane.start = AsyncMock()
    ws_hub = MagicMock()
    ws_hub.run = AsyncMock(side_effect=asyncio.CancelledError)
    run_recorder = MagicMock()
    run_recorder.run = AsyncMock(side_effect=asyncio.CancelledError)
    gps_monitor = MagicMock()
    gps_monitor.run = AsyncMock(side_effect=asyncio.CancelledError)
    update_manager = MagicMock()
    update_manager.startup_recover = AsyncMock()
    update_manager.job_task = None

    rt, lifecycle = _make_runtime(
        control_plane=control_plane,
        ws_hub=ws_hub,
        run_recorder=run_recorder,
        gps_monitor=gps_monitor,
        update_manager=update_manager,
    )
    lifecycle._start_udp_receiver = _fake_udp

    await lifecycle.start()
    assert len(lifecycle.tasks) == 5
    control_plane.start.assert_called_once()
    assert rt.health_state.startup_state == "ready"
    assert rt.health_state.startup_phase == "ready"

    await lifecycle.stop()


@pytest.mark.asyncio
async def test_start_follows_declared_startup_phase_order(monkeypatch) -> None:
    import vibesensor.infra.runtime as runtime_module

    observed_phases: list[str] = []

    async def _fake_udp(*args, **kwargs):
        return None, None

    control_plane = MagicMock()
    control_plane.start = AsyncMock()
    ws_hub = MagicMock()
    ws_hub.run = AsyncMock(side_effect=asyncio.CancelledError)
    run_recorder = MagicMock()
    run_recorder.run = AsyncMock(side_effect=asyncio.CancelledError)
    gps_monitor = MagicMock()
    gps_monitor.run = AsyncMock(side_effect=asyncio.CancelledError)
    update_manager = MagicMock()
    update_manager.startup_recover = AsyncMock()
    update_manager.job_task = None

    rt, lifecycle = _make_runtime(
        control_plane=control_plane,
        ws_hub=ws_hub,
        run_recorder=run_recorder,
        gps_monitor=gps_monitor,
        update_manager=update_manager,
    )
    lifecycle._start_udp_receiver = _fake_udp

    original_set_phase = runtime_module.RuntimeHealthState.set_phase

    def _record_phase(self, phase: str) -> None:
        observed_phases.append(phase)
        original_set_phase(self, phase)

    monkeypatch.setattr(runtime_module.RuntimeHealthState, "set_phase", _record_phase)

    await lifecycle.start()

    assert observed_phases == [
        "starting",
        "udp_receiver",
        "control_plane",
        "processing-loop",
        "ws-broadcast",
        "metrics-log",
        "gps-speed",
        "update-startup-recover",
    ]
    assert rt.health_state.startup_state == "ready"
    assert rt.health_state.startup_phase == "ready"

    await lifecycle.stop()


@pytest.mark.asyncio
async def test_start_records_background_task_failure(monkeypatch) -> None:
    import vibesensor.infra.runtime.lifecycle as lifecycle_module

    async def _fake_udp(*args, **kwargs):
        return None, None

    control_plane = MagicMock()
    control_plane.start = AsyncMock()
    ws_hub = MagicMock()

    async def _failing_ws(*args, **kwargs):
        raise RuntimeError("ws boom")

    ws_hub.run = AsyncMock(side_effect=_failing_ws)
    run_recorder = MagicMock()
    run_recorder.run = AsyncMock(side_effect=asyncio.CancelledError)
    gps_monitor = MagicMock()
    gps_monitor.run = AsyncMock(side_effect=asyncio.CancelledError)
    update_manager = MagicMock()
    update_manager.startup_recover = AsyncMock()
    update_manager.job_task = None

    rt, lifecycle = _make_runtime(
        control_plane=control_plane,
        ws_hub=ws_hub,
        run_recorder=run_recorder,
        gps_monitor=gps_monitor,
        update_manager=update_manager,
    )
    lifecycle._start_udp_receiver = _fake_udp

    monkeypatch.setattr(lifecycle_module, "_TASK_RESTART_MAX_ATTEMPTS", 0)

    await lifecycle.start()
    failed_task = next(task for task in lifecycle.tasks if task.get_name() == "ws-broadcast")
    await asyncio.gather(failed_task, return_exceptions=True)

    assert rt.health_state.background_task_failures["ws-broadcast"] == "ws boom"

    await lifecycle.stop()


@pytest.mark.asyncio
async def test_start_restarts_supervised_task_after_failure(monkeypatch) -> None:
    import vibesensor.infra.runtime.lifecycle as lifecycle_module

    async def _fake_udp(*args, **kwargs):
        return None, None

    control_plane = MagicMock()
    control_plane.start = AsyncMock()
    restart_started = asyncio.Event()
    ws_hub = MagicMock()
    ws_run_calls = {"count": 0}
    original_sleep = asyncio.sleep

    async def _ws_run(*args, **kwargs):
        ws_run_calls["count"] += 1
        if ws_run_calls["count"] == 1:
            raise RuntimeError("ws boom")
        restart_started.set()
        await asyncio.Future()

    async def _fast_sleep(delay: float) -> None:
        await original_sleep(0)

    ws_hub.run = _ws_run
    run_recorder = MagicMock()
    run_recorder.run = AsyncMock(side_effect=asyncio.CancelledError)
    gps_monitor = MagicMock()
    gps_monitor.run = AsyncMock(side_effect=asyncio.CancelledError)
    update_manager = MagicMock()
    update_manager.startup_recover = AsyncMock()
    update_manager.job_task = None

    rt, lifecycle = _make_runtime(
        control_plane=control_plane,
        ws_hub=ws_hub,
        run_recorder=run_recorder,
        gps_monitor=gps_monitor,
        update_manager=update_manager,
    )
    lifecycle._start_udp_receiver = _fake_udp

    monkeypatch.setattr(lifecycle_module, "_TASK_RESTART_BASE_DELAY_S", 0.0)
    monkeypatch.setattr(lifecycle_module, "_TASK_RESTART_MAX_DELAY_S", 0.0)
    monkeypatch.setattr(lifecycle_module.asyncio, "sleep", _fast_sleep)

    await lifecycle.start()
    await asyncio.wait_for(restart_started.wait(), timeout=1.0)

    assert ws_run_calls["count"] == 2
    assert rt.health_state.background_task_failures == {}

    await lifecycle.stop()


@pytest.mark.asyncio
async def test_start_monitors_udp_consumer_failure(monkeypatch) -> None:
    consumer_started = asyncio.Event()

    async def _consumer() -> None:
        consumer_started.set()
        raise RuntimeError("udp boom")

    async def _fake_udp(*args, **kwargs):
        return MagicMock(), asyncio.create_task(_consumer(), name="udp-data-consumer")

    control_plane = MagicMock()
    control_plane.start = AsyncMock()
    ws_hub = MagicMock()
    ws_hub.run = AsyncMock(side_effect=asyncio.CancelledError)
    run_recorder = MagicMock()
    run_recorder.run = AsyncMock(side_effect=asyncio.CancelledError)
    gps_monitor = MagicMock()
    gps_monitor.run = AsyncMock(side_effect=asyncio.CancelledError)
    update_manager = MagicMock()
    update_manager.startup_recover = AsyncMock()
    update_manager.job_task = None

    rt, lifecycle = _make_runtime(
        control_plane=control_plane,
        ws_hub=ws_hub,
        run_recorder=run_recorder,
        gps_monitor=gps_monitor,
        update_manager=update_manager,
    )
    lifecycle._start_udp_receiver = _fake_udp

    await lifecycle.start()
    await asyncio.wait_for(consumer_started.wait(), timeout=1.0)
    if lifecycle._data_consumer_task is not None:
        await asyncio.gather(lifecycle._data_consumer_task, return_exceptions=True)

    assert rt.health_state.background_task_failures["udp-data-consumer"] == "udp boom"

    await lifecycle.stop()


@pytest.mark.asyncio
async def test_stop_cancels_tasks_and_closes_resources(monkeypatch) -> None:
    """LifecycleManager.stop() should cancel tasks, close DB and worker pool."""

    async def _fake_udp(*args, **kwargs):
        return MagicMock(), None

    run_recorder = MagicMock()
    run_recorder.shutdown_report = MagicMock(
        return_value=MagicMock(
            completed=True,
            analysis_queue_depth=0,
            analysis_active_run_id=None,
            analysis_queue_oldest_age_s=None,
            active_run_id_before_stop=None,
            write_error=None,
        ),
    )

    history_db = MagicMock()
    worker_pool = MagicMock()
    control_plane = MagicMock()
    control_plane.start = AsyncMock()
    control_plane.close = MagicMock()
    update_manager = MagicMock()
    update_manager.job_task = None
    esp_flash_manager = MagicMock()
    esp_flash_manager.job_task = None

    ws_hub = MagicMock()
    ws_hub.run = AsyncMock(side_effect=asyncio.CancelledError)
    gps_monitor = MagicMock()
    gps_monitor.run = AsyncMock(side_effect=asyncio.CancelledError)
    run_recorder.run = AsyncMock(side_effect=asyncio.CancelledError)
    update_manager.startup_recover = AsyncMock()

    rt, lifecycle = _make_runtime(
        control_plane=control_plane,
        ws_hub=ws_hub,
        run_recorder=run_recorder,
        gps_monitor=gps_monitor,
        update_manager=update_manager,
        esp_flash_manager=esp_flash_manager,
        history_db=history_db,
        worker_pool=worker_pool,
    )
    lifecycle._start_udp_receiver = _fake_udp

    await lifecycle.start()
    assert len(lifecycle.tasks) > 0

    await lifecycle.stop()
    assert lifecycle.tasks == []
    run_recorder.shutdown_report.assert_called_once_with(5.0)
    worker_pool.shutdown.assert_called_once_with(True)
    history_db.close.assert_called_once()


@pytest.mark.parametrize("attr", ["settings_store", "processing_loop", "ws_broadcast"])
def test_runtime_state_has_public_attribute(attr: str) -> None:
    """Canonical import path should expose key public attributes."""
    from vibesensor.app.runtime_state import RuntimeState

    assert hasattr(RuntimeState, attr), f"RuntimeState missing {attr}"


def test_runtime_state_uses_focused_ports_for_read_side_runtime_fields() -> None:
    """RuntimeState should expose existing shared ports for read-side services."""
    from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor
    from vibesensor.adapters.persistence.history_db import HistoryDB
    from vibesensor.adapters.udp.udp_control_tx import UDPControlPlane
    from vibesensor.adapters.websocket.hub import WebSocketHub
    from vibesensor.app import runtime_state as runtime_state_module
    from vibesensor.app.runtime_state import RuntimeState
    from vibesensor.app.settings import AppConfig
    from vibesensor.shared.ports import ClientTracker, SettingsReader, SignalSource

    hints = get_type_hints(
        RuntimeState,
        globalns={
            **vars(runtime_state_module),
            "AppConfig": AppConfig,
            "GPSSpeedMonitor": GPSSpeedMonitor,
            "HistoryDB": HistoryDB,
            "UDPControlPlane": UDPControlPlane,
            "WebSocketHub": WebSocketHub,
        },
    )
    assert hints["registry"] is ClientTracker
    assert hints["processor"] is SignalSource
    assert hints["settings_store"] is SettingsReader
