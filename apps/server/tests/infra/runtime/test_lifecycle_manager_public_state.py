"""Public-state lifecycle manager coverage for startup, supervision, and cleanup."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from test_support.runtime_lifecycle import (
    build_runtime as _make_runtime,
)

from vibesensor.infra.runtime.lifecycle import LifecycleManager
from vibesensor.shared.runtime_failures import BroadcastTickLoopFailure


async def _park_forever(*args, **kwargs) -> None:
    await asyncio.Event().wait()


async def _wait_until(predicate, *, spins: int = 40) -> None:
    for _ in range(spins):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition not met")


def _build_lifecycle(*, start_udp_receiver, **overrides):
    runtime_state, _ = _make_runtime(**overrides)
    lifecycle = LifecycleManager(
        runtime=runtime_state.lifecycle_runtime(),
        start_udp_receiver=start_udp_receiver,
    )
    return runtime_state, lifecycle


@pytest.mark.asyncio
async def test_start_marks_runtime_ready_and_tracks_running_tasks() -> None:
    async def _fake_udp(*args, **kwargs):
        return None, None

    control_plane = MagicMock()
    control_plane.start = AsyncMock()
    ws_hub = MagicMock()
    ws_hub.run = AsyncMock(side_effect=_park_forever)
    run_recorder = MagicMock()
    run_recorder.run = AsyncMock(side_effect=_park_forever)
    gps_monitor = MagicMock()
    gps_monitor.run = AsyncMock(side_effect=_park_forever)
    obd_runner = MagicMock()
    obd_runner.run = AsyncMock(side_effect=_park_forever)
    update_manager = MagicMock()
    update_manager.startup_recover = AsyncMock()
    update_manager.job_task = None

    runtime_state, lifecycle = _build_lifecycle(
        start_udp_receiver=_fake_udp,
        control_plane=control_plane,
        ws_hub=ws_hub,
        run_recorder=run_recorder,
        gps_monitor=gps_monitor,
        obd_runner=obd_runner,
        update_manager=update_manager,
    )

    await lifecycle.start()
    try:
        await _wait_until(lambda: "processing-loop" in lifecycle.tasks)

        assert {
            "processing-loop",
            "ws-broadcast",
            "metrics-log",
            "gps-speed",
            "obd-speed",
        }.issubset(set(lifecycle.tasks))
        assert runtime_state.health_state.startup_state == "ready"
        assert runtime_state.health_state.startup_phase == "ready"
    finally:
        await lifecycle.stop()


@pytest.mark.asyncio
async def test_start_records_background_task_failure_in_health_state() -> None:
    async def _fake_udp(*args, **kwargs):
        return None, None

    control_plane = MagicMock()
    control_plane.start = AsyncMock()

    async def _failing_ws(*args, **kwargs):
        raise RuntimeError("ws boom")

    ws_hub = MagicMock()
    ws_hub.run = AsyncMock(side_effect=_failing_ws)
    run_recorder = MagicMock()
    run_recorder.run = AsyncMock(side_effect=_park_forever)
    gps_monitor = MagicMock()
    gps_monitor.run = AsyncMock(side_effect=_park_forever)
    obd_runner = MagicMock()
    obd_runner.run = AsyncMock(side_effect=_park_forever)
    update_manager = MagicMock()
    update_manager.startup_recover = AsyncMock()
    update_manager.job_task = None

    runtime_state, lifecycle = _build_lifecycle(
        start_udp_receiver=_fake_udp,
        control_plane=control_plane,
        ws_hub=ws_hub,
        run_recorder=run_recorder,
        gps_monitor=gps_monitor,
        obd_runner=obd_runner,
        update_manager=update_manager,
    )

    await lifecycle.start()
    try:
        await _wait_until(
            lambda: "ws-broadcast" in runtime_state.health_state.background_task_failures
        )

        assert runtime_state.health_state.background_task_failures["ws-broadcast"] == "ws boom"
    finally:
        await lifecycle.stop()


@pytest.mark.asyncio
async def test_start_clears_restartable_failure_after_successful_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    run_recorder.run = AsyncMock(side_effect=_park_forever)
    gps_monitor = MagicMock()
    gps_monitor.run = AsyncMock(side_effect=_park_forever)
    obd_runner = MagicMock()
    obd_runner.run = AsyncMock(side_effect=_park_forever)
    update_manager = MagicMock()
    update_manager.startup_recover = AsyncMock()
    update_manager.job_task = None

    runtime_state, lifecycle = _build_lifecycle(
        start_udp_receiver=_fake_udp,
        control_plane=control_plane,
        ws_hub=ws_hub,
        run_recorder=run_recorder,
        gps_monitor=gps_monitor,
        obd_runner=obd_runner,
        update_manager=update_manager,
    )
    monkeypatch.setattr("vibesensor.infra.runtime.task_supervisor.anyio.sleep", _fast_sleep)

    await lifecycle.start()
    try:
        await asyncio.wait_for(restart_started.wait(), timeout=1.0)

        assert ws_run_calls["count"] == 2
        assert runtime_state.health_state.background_task_failures == {}
    finally:
        await lifecycle.stop()


@pytest.mark.asyncio
async def test_stop_cleans_owned_resources_once_and_clears_public_tasks() -> None:
    transport = MagicMock()

    async def _fake_udp(*args, **kwargs):
        return transport, None

    shutdown_report = MagicMock(
        completed=True,
        analysis_queue_depth=0,
        analysis_active_run_id=None,
        analysis_queue_oldest_age_s=None,
        active_run_id_before_stop=None,
        write_error=None,
    )
    run_recorder = MagicMock()
    run_recorder.run = AsyncMock(side_effect=_park_forever)
    run_recorder.shutdown_report = MagicMock(return_value=shutdown_report)
    history_db = MagicMock()
    history_db.aclose = AsyncMock()
    worker_pool = MagicMock()
    control_plane = MagicMock()
    control_plane.start = AsyncMock()
    control_plane.close = MagicMock()
    ws_hub = MagicMock()
    ws_hub.run = AsyncMock(side_effect=_park_forever)
    gps_monitor = MagicMock()
    gps_monitor.run = AsyncMock(side_effect=_park_forever)
    obd_runner = MagicMock()
    obd_runner.run = AsyncMock(side_effect=_park_forever)
    update_manager = MagicMock()
    update_manager.startup_recover = AsyncMock()
    update_manager.job_task = None
    esp_flash_manager = MagicMock()
    esp_flash_manager.job_task = None

    _runtime_state, lifecycle = _build_lifecycle(
        start_udp_receiver=_fake_udp,
        control_plane=control_plane,
        ws_hub=ws_hub,
        run_recorder=run_recorder,
        gps_monitor=gps_monitor,
        obd_runner=obd_runner,
        update_manager=update_manager,
        esp_flash_manager=esp_flash_manager,
        history_db=history_db,
        worker_pool=worker_pool,
    )

    await lifecycle.start()
    try:
        await _wait_until(lambda: bool(lifecycle.tasks))
    finally:
        await lifecycle.stop()

    assert lifecycle.tasks == []
    run_recorder.shutdown_report.assert_called_once_with(5.0)
    worker_pool.shutdown.assert_called_once_with(True)
    history_db.aclose.assert_called_once()
    transport.close.assert_called_once()
