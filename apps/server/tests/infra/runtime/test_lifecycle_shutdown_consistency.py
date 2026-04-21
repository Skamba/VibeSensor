"""Verify lifecycle shutdown logs lingering managed tasks consistently."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.lifecycle import LifecycleManager, LifecycleRuntime


def _make_lifecycle() -> LifecycleManager:
    health_state = RuntimeHealthState()
    health_state.mark_ready()
    runtime = LifecycleRuntime(
        health_state=health_state,
        history_db_path=None,
        udp_data_host="0.0.0.0",
        udp_data_port=9000,
        udp_data_queue_maxsize=64,
        gpsd_host="127.0.0.1",
        gpsd_port=2947,
        shutdown_analysis_timeout_s=5.0,
        registry=MagicMock(),
        processor=MagicMock(),
        control_plane=MagicMock(close=MagicMock()),
        processing_loop=MagicMock(),
        ws_hub=MagicMock(),
        ws_broadcast=MagicMock(),
        run_recorder=MagicMock(
            shutdown_report=MagicMock(
                return_value=SimpleNamespace(
                    completed=True,
                    analysis_queue_depth=0,
                    analysis_active_run_id=None,
                    analysis_queue_oldest_age_s=None,
                    active_run_id_before_stop=None,
                    write_error=None,
                ),
            ),
        ),
        gps_monitor=MagicMock(),
        obd_runner=MagicMock(),
        update_manager=MagicMock(job_task=None),
        esp_flash_manager=MagicMock(job_task=None),
        worker_pool=MagicMock(),
        history_db=MagicMock(aclose=AsyncMock()),
    )
    return LifecycleManager(runtime=runtime, start_udp_receiver=MagicMock())


async def _stubborn_task() -> None:
    first_wait = asyncio.Event()
    second_wait = asyncio.Event()
    try:
        await first_wait.wait()
    except asyncio.CancelledError:
        await second_wait.wait()


@pytest.mark.asyncio
async def test_stop_logs_managed_jobs_that_outlive_cancel_timeout(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import vibesensor.infra.runtime.lifecycle as lifecycle_module

    lifecycle = _make_lifecycle()
    managed = asyncio.create_task(_stubborn_task(), name="system-update")
    lifecycle._runtime.update_manager = MagicMock(job_task=managed)
    await asyncio.sleep(0)

    async def _wait_pending(tasks, timeout):
        del timeout
        await asyncio.sleep(0)
        return set(), set(tasks)

    monkeypatch.setattr(lifecycle_module.asyncio, "wait", _wait_pending)

    with caplog.at_level(logging.WARNING):
        await lifecycle.stop()

    assert "managed shutdown task(s)" in caplog.text
    assert "system-update" in caplog.text
    assert "lingering tasks" in caplog.text

    managed.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await managed
