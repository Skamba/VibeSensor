"""Public-state lifecycle manager coverage for startup, supervision, and cleanup."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest
from test_support.runtime_lifecycle import (
    build_runtime as _make_runtime,
)

from vibesensor.app.lifecycle import LifecycleManager
from vibesensor.history.history_db import HistoryDB
from vibesensor.ingest.udp_control_tx import UDPControlPlane
from vibesensor.live.broadcaster import LiveBroadcaster
from vibesensor.live.runtime_failures import BroadcastTickLoopFailure
from vibesensor.recording.raw_capture_writer import RunRawCaptureWriter
from vibesensor.recording.recorder import RunRecorder
from vibesensor.speed.gps_speed import GPSSpeedMonitor
from vibesensor.speed.obd.service import ObdService
from vibesensor.updates.firmware.esp_flash_manager import EspFlashManager
from vibesensor.updates.manager import UpdateManager


async def _park_forever(*args, **kwargs) -> None:
    await asyncio.Event().wait()


async def _wait_until(predicate, *, timeout_s: float = 10.0) -> None:
    """Yield to the loop until *predicate* holds; bounded by time, not loop turns.

    Startup hands work to threads, so a fixed number of loop turns is not enough
    on a loaded machine.
    """
    deadline = time.monotonic() + timeout_s
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met")
        await asyncio.sleep(0.001)


def _build_lifecycle(*, start_udp_receiver, **overrides):
    runtime, _ = _make_runtime(**overrides)
    lifecycle = LifecycleManager(
        runtime=runtime,
        start_udp_receiver=start_udp_receiver,
    )
    return runtime, lifecycle


@pytest.mark.asyncio
async def test_start_marks_runtime_ready_and_tracks_running_tasks() -> None:
    async def _fake_udp(*args, **kwargs):
        return None, None

    control_plane = create_autospec(UDPControlPlane, instance=True)
    control_plane.start = AsyncMock()
    ws_broadcaster = create_autospec(LiveBroadcaster, instance=True)
    ws_broadcaster.run = AsyncMock(side_effect=_park_forever)
    run_recorder = create_autospec(RunRecorder, instance=True)
    run_recorder.raw_capture = create_autospec(RunRawCaptureWriter, instance=True)
    run_recorder.run = AsyncMock(side_effect=_park_forever)
    gps_monitor = create_autospec(GPSSpeedMonitor, instance=True)
    gps_monitor.run = AsyncMock(side_effect=_park_forever)
    obd_runner = create_autospec(ObdService, instance=True)
    obd_runner.run = AsyncMock(side_effect=_park_forever)
    update_manager = create_autospec(UpdateManager, instance=True)
    update_manager.startup_recover = AsyncMock()
    update_manager.job_task = None

    runtime_state, lifecycle = _build_lifecycle(
        start_udp_receiver=_fake_udp,
        control_plane=control_plane,
        ws_broadcaster=ws_broadcaster,
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

    control_plane = create_autospec(UDPControlPlane, instance=True)
    control_plane.start = AsyncMock()

    async def _failing_ws(*args, **kwargs):
        raise RuntimeError("ws boom")

    ws_broadcaster = create_autospec(LiveBroadcaster, instance=True)
    ws_broadcaster.run = AsyncMock(side_effect=_failing_ws)
    run_recorder = create_autospec(RunRecorder, instance=True)
    run_recorder.raw_capture = create_autospec(RunRawCaptureWriter, instance=True)
    run_recorder.run = AsyncMock(side_effect=_park_forever)
    gps_monitor = create_autospec(GPSSpeedMonitor, instance=True)
    gps_monitor.run = AsyncMock(side_effect=_park_forever)
    obd_runner = create_autospec(ObdService, instance=True)
    obd_runner.run = AsyncMock(side_effect=_park_forever)
    update_manager = create_autospec(UpdateManager, instance=True)
    update_manager.startup_recover = AsyncMock()
    update_manager.job_task = None

    runtime_state, lifecycle = _build_lifecycle(
        start_udp_receiver=_fake_udp,
        control_plane=control_plane,
        ws_broadcaster=ws_broadcaster,
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

    control_plane = create_autospec(UDPControlPlane, instance=True)
    control_plane.start = AsyncMock()
    restart_started = asyncio.Event()
    ws_broadcaster = create_autospec(LiveBroadcaster, instance=True)
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

    ws_broadcaster.run = _ws_run
    run_recorder = create_autospec(RunRecorder, instance=True)
    run_recorder.raw_capture = create_autospec(RunRawCaptureWriter, instance=True)
    run_recorder.run = AsyncMock(side_effect=_park_forever)
    gps_monitor = create_autospec(GPSSpeedMonitor, instance=True)
    gps_monitor.run = AsyncMock(side_effect=_park_forever)
    obd_runner = create_autospec(ObdService, instance=True)
    obd_runner.run = AsyncMock(side_effect=_park_forever)
    update_manager = create_autospec(UpdateManager, instance=True)
    update_manager.startup_recover = AsyncMock()
    update_manager.job_task = None

    runtime_state, lifecycle = _build_lifecycle(
        start_udp_receiver=_fake_udp,
        control_plane=control_plane,
        ws_broadcaster=ws_broadcaster,
        run_recorder=run_recorder,
        gps_monitor=gps_monitor,
        obd_runner=obd_runner,
        update_manager=update_manager,
    )
    monkeypatch.setattr("vibesensor.app.background_tasks.anyio.sleep", _fast_sleep)

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
    run_recorder = create_autospec(RunRecorder, instance=True)
    run_recorder.raw_capture = create_autospec(RunRawCaptureWriter, instance=True)
    run_recorder.run = AsyncMock(side_effect=_park_forever)
    run_recorder.shutdown_report = MagicMock(return_value=shutdown_report)
    history_db = create_autospec(HistoryDB, instance=True)
    control_plane = create_autospec(UDPControlPlane, instance=True)
    control_plane.start = AsyncMock()
    control_plane.close = MagicMock()
    ws_broadcaster = create_autospec(LiveBroadcaster, instance=True)
    ws_broadcaster.run = AsyncMock(side_effect=_park_forever)
    gps_monitor = create_autospec(GPSSpeedMonitor, instance=True)
    gps_monitor.run = AsyncMock(side_effect=_park_forever)
    obd_runner = create_autospec(ObdService, instance=True)
    obd_runner.run = AsyncMock(side_effect=_park_forever)
    update_manager = create_autospec(UpdateManager, instance=True)
    update_manager.startup_recover = AsyncMock()
    update_manager.job_task = None
    esp_flash_manager = create_autospec(EspFlashManager, instance=True)
    esp_flash_manager.job_task = None

    _runtime_state, lifecycle = _build_lifecycle(
        start_udp_receiver=_fake_udp,
        control_plane=control_plane,
        ws_broadcaster=ws_broadcaster,
        run_recorder=run_recorder,
        gps_monitor=gps_monitor,
        obd_runner=obd_runner,
        update_manager=update_manager,
        esp_flash_manager=esp_flash_manager,
        history_db=history_db,
    )

    await lifecycle.start()
    try:
        await _wait_until(lambda: bool(lifecycle.tasks))
    finally:
        await lifecycle.stop()

    assert lifecycle.tasks == []
    run_recorder.shutdown_report.assert_called_once_with(5.0)
    history_db.close.assert_called_once()
    transport.close.assert_called_once()
