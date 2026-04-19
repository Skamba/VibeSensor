"""Tests for vibesensor.infra.runtime – RuntimeState lifecycle and processing loop.

These tests verify the newly extracted RuntimeState methods that were
previously nested closures inside create_app() and therefore untestable
in isolation.
"""

from __future__ import annotations

import asyncio
from typing import get_type_hints
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from test_support.runtime_lifecycle import (
    StubConfig as _StubConfig,
)
from test_support.runtime_lifecycle import (
    StubProcessingConfig as _StubProcessingConfig,
)
from test_support.runtime_lifecycle import (
    StubProcessor as _StubProcessor,
)
from test_support.runtime_lifecycle import (
    build_runtime as _make_runtime,
)

from vibesensor.shared.exceptions import ProcessingError
from vibesensor.shared.runtime_failures import BroadcastTickLoopFailure

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
        raise ProcessingError("test failure")

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
    lifecycle._udp_transport_lifecycle._start_udp_receiver = _fake_udp

    await lifecycle.start()
    assert len(lifecycle.tasks) == 6
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
    lifecycle._udp_transport_lifecycle._start_udp_receiver = _fake_udp

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
        "obd-speed",
        "update-startup-recover",
    ]
    assert rt.health_state.startup_state == "ready"
    assert rt.health_state.startup_phase == "ready"

    await lifecycle.stop()


@pytest.mark.asyncio
async def test_start_records_background_task_failure(monkeypatch) -> None:
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
    lifecycle._udp_transport_lifecycle._start_udp_receiver = _fake_udp

    lifecycle._task_supervisor._max_attempts = 0

    await lifecycle.start()
    failed_task = next(task for task in lifecycle.tasks if task.get_name() == "ws-broadcast")
    await asyncio.gather(failed_task, return_exceptions=True)

    assert rt.health_state.background_task_failures["ws-broadcast"] == "ws boom"

    await lifecycle.stop()


@pytest.mark.asyncio
async def test_start_restarts_supervised_task_after_failure(monkeypatch) -> None:
    import vibesensor.infra.runtime.task_supervisor as task_supervisor_module

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
            raise BroadcastTickLoopFailure(
                consecutive_failures=10,
                cause=OSError("ws boom"),
            )
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
    lifecycle._udp_transport_lifecycle._start_udp_receiver = _fake_udp

    lifecycle._task_supervisor._base_delay_s = 0.0
    lifecycle._task_supervisor._max_delay_s = 0.0
    monkeypatch.setattr(task_supervisor_module.asyncio, "sleep", _fast_sleep)

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
    lifecycle._udp_transport_lifecycle._start_udp_receiver = _fake_udp

    await lifecycle.start()
    await asyncio.wait_for(consumer_started.wait(), timeout=1.0)
    consumer_task = lifecycle._udp_transport_lifecycle.consumer_task
    if consumer_task is not None:
        await asyncio.gather(consumer_task, return_exceptions=True)
    # Yield so the done-callback that records the failure can fire.
    await asyncio.sleep(0)

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
    lifecycle._udp_transport_lifecycle._start_udp_receiver = _fake_udp

    await lifecycle.start()
    assert len(lifecycle.tasks) > 0

    await lifecycle.stop()
    assert lifecycle.tasks == []
    run_recorder.shutdown_report.assert_called_once_with(5.0)
    worker_pool.shutdown.assert_called_once_with(True)
    history_db.close.assert_called_once()


@pytest.mark.parametrize("attr", ["settings_reader", "processing_loop", "ws_broadcast"])
def test_runtime_state_has_public_attribute(attr: str) -> None:
    """Canonical import path should expose key public attributes."""
    from vibesensor.app.runtime_state import RuntimeState

    assert hasattr(RuntimeState, attr), f"RuntimeState missing {attr}"


def test_runtime_state_uses_focused_ports_for_read_side_runtime_fields() -> None:
    """RuntimeState should expose existing shared ports for read-side services."""
    from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor
    from vibesensor.adapters.udp.udp_control_tx import UDPControlPlane
    from vibesensor.adapters.websocket.hub import WebSocketHub
    from vibesensor.app import runtime_state as runtime_state_module
    from vibesensor.app.runtime_state import RuntimeState
    from vibesensor.app.settings import AppConfig
    from vibesensor.infra.runtime.lifecycle import LifecycleHistoryDb, LifecycleObdRunner
    from vibesensor.shared.ports import ClientTracker, SettingsReader, SignalSource

    hints = get_type_hints(
        RuntimeState,
        globalns={
            **vars(runtime_state_module),
            "AppConfig": AppConfig,
            "GPSSpeedMonitor": GPSSpeedMonitor,
            "LifecycleHistoryDb": LifecycleHistoryDb,
            "LifecycleObdRunner": LifecycleObdRunner,
            "UDPControlPlane": UDPControlPlane,
            "WebSocketHub": WebSocketHub,
        },
    )
    assert hints["registry"] is ClientTracker
    assert hints["processor"] is SignalSource
    assert hints["settings_reader"] is SettingsReader
