from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from test_support.tracing import configured_trace_output, read_trace_output

from vibesensor.shared.exceptions import UpdateCleanupError, UpdateError
from vibesensor.use_cases.updates.manager import UpdateManager
from vibesensor.use_cases.updates.models import UpdateRequest, UpdateState, UpdateTransport


def _wifi_request(ssid: str = "TestNet", password: str = "pass123") -> UpdateRequest:
    return UpdateRequest(
        transport=UpdateTransport.wifi,
        ssid=ssid,
        password=password,
    )


def _build_manager(
    *,
    timeout_s: float = 10.0,
) -> tuple[UpdateManager, MagicMock, MagicMock, AsyncMock]:
    tracker = MagicMock()
    tracker.status = MagicMock()
    tracker.status.state = UpdateState.running
    reporter = MagicMock()
    workflow_run = AsyncMock()
    manager = UpdateManager(
        status=tracker,
        reporter=reporter,
        workflow=SimpleNamespace(run=workflow_run),
        startup_recovery=SimpleNamespace(recover=AsyncMock()),
        usb_status_service=MagicMock(),
        timeout_s=timeout_s,
    )
    return manager, tracker, reporter, workflow_run


@pytest.mark.asyncio
async def test_start_rejects_concurrent_job() -> None:
    manager, tracker, reporter, workflow_run = _build_manager()
    request = _wifi_request()
    started = asyncio.Event()
    release = asyncio.Event()

    async def running_workflow(*, request: UpdateRequest) -> None:
        assert request == _wifi_request()
        started.set()
        await release.wait()

    workflow_run.side_effect = running_workflow
    manager.start(request.ssid, request.password, transport=request.transport)
    task = manager.job_task
    assert task is not None
    await asyncio.wait_for(started.wait(), timeout=1.0)

    with pytest.raises(UpdateError, match="already in progress"):
        manager.start(request.ssid, request.password, transport=request.transport)

    assert manager.cancel() is True
    with contextlib.suppress(asyncio.CancelledError):
        await task
    tracker.start_job.assert_called_once_with(request)
    tracker.track_secret.assert_called_once_with(request.password)
    reporter.fail_cancelled.assert_called_once_with()


@pytest.mark.asyncio
async def test_timeout_marks_failure_and_finishes_lifecycle() -> None:
    async def slow_workflow(*, request: UpdateRequest) -> None:
        assert request == _wifi_request()
        await asyncio.sleep(1.0)

    manager, tracker, reporter, workflow_run = _build_manager(timeout_s=0.01)
    workflow_run.side_effect = slow_workflow
    request = _wifi_request()
    manager.start(request.ssid, request.password, transport=request.transport)
    task = manager.job_task
    assert task is not None
    await task

    reporter.fail_timeout.assert_called_once_with(timeout_s=0.01)
    tracker.clear_secrets.assert_called_once_with()
    tracker.finish_cleanup.assert_called_once_with()


@pytest.mark.asyncio
async def test_update_error_marks_failure_without_propagating() -> None:
    manager, tracker, reporter, workflow_run = _build_manager()
    error = UpdateError("transport failed")
    workflow_run.side_effect = error
    request = _wifi_request()
    manager.start(request.ssid, request.password, transport=request.transport)
    task = manager.job_task
    assert task is not None
    await task

    reporter.fail.assert_called_once_with(error, default_phase="workflow")
    tracker.clear_secrets.assert_called_once_with()
    tracker.finish_cleanup.assert_called_once_with()


@pytest.mark.asyncio
async def test_cleanup_error_propagates_explicitly() -> None:
    manager, tracker, reporter, workflow_run = _build_manager()
    error = UpdateCleanupError("transport cleanup failed")
    workflow_run.side_effect = error
    request = _wifi_request()
    manager.start(request.ssid, request.password, transport=request.transport)
    task = manager.job_task
    assert task is not None

    with pytest.raises(UpdateCleanupError, match="transport cleanup failed"):
        await task

    reporter.fail.assert_called_once_with(error, default_phase="cleanup")
    tracker.clear_secrets.assert_called_once_with()
    tracker.finish_cleanup.assert_called_once_with()


@pytest.mark.asyncio
async def test_start_exports_update_workflow_trace_span(tmp_path: Path) -> None:
    manager, tracker, reporter, workflow_run = _build_manager()
    request = _wifi_request()

    with configured_trace_output(tmp_path) as trace_path:
        manager.start(request.ssid, request.password, transport=request.transport)
        task = manager.job_task
        assert task is not None
        await task

    workflow_run.assert_awaited_once_with(request=request)
    tracker.clear_secrets.assert_called_once_with()
    tracker.finish_cleanup.assert_called_once_with()
    assert reporter.fail.call_count == 0
    span = next(item for item in read_trace_output(trace_path) if item["name"] == "update.workflow")
    assert span["attributes"]["vibesensor.transport"] == "wifi"
