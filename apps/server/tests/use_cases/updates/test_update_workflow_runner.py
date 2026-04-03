from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from vibesensor.shared.exceptions import UpdateCleanupError, UpdateError
from vibesensor.use_cases.updates.models import UpdateRequest, UpdateTransport
from vibesensor.use_cases.updates.workflow_runner import UpdateWorkflowContext, UpdateWorkflowRunner


def _wifi_request(ssid: str = "TestNet", password: str = "pass123") -> UpdateRequest:
    return UpdateRequest(
        transport=UpdateTransport.wifi,
        ssid=ssid,
        password=password,
    )


@pytest.mark.asyncio
async def test_start_rejects_concurrent_job() -> None:
    controller = MagicMock()
    recorder = MagicMock()
    cleanup = AsyncMock()
    runner = UpdateWorkflowRunner(
        status_controller=controller,
        status_recorder=recorder,
        cleanup=cleanup,
        timeout_s=10.0,
    )
    request = _wifi_request()
    started = asyncio.Event()
    release = asyncio.Event()

    async def running_workflow(_context: UpdateWorkflowContext) -> None:
        started.set()
        await release.wait()

    runner.start(request=request, workflow=running_workflow)
    task = runner.job_task
    assert task is not None
    await asyncio.wait_for(started.wait(), timeout=1.0)

    with pytest.raises(UpdateError, match="already in progress"):
        runner.start(request=request, workflow=running_workflow)

    assert runner.cancel() is True
    with contextlib.suppress(asyncio.CancelledError):
        await task
    controller.start_job.assert_called_once_with(request)
    recorder.track_secret.assert_called_once_with(request.password)


@pytest.mark.asyncio
async def test_timeout_marks_failure_and_runs_cleanup() -> None:
    controller = MagicMock()
    recorder = MagicMock()
    cleanup = AsyncMock()
    runner = UpdateWorkflowRunner(
        status_controller=controller,
        status_recorder=recorder,
        cleanup=cleanup,
        timeout_s=0.01,
    )

    async def slow_workflow(_context: UpdateWorkflowContext) -> None:
        await asyncio.sleep(1.0)

    runner.start(request=_wifi_request(), workflow=slow_workflow)
    task = runner.job_task
    assert task is not None
    await task

    recorder.add_issue.assert_any_call("timeout", "Update timed out after 0.01s")
    recorder.log.assert_any_call("Update timed out after 0.01s")
    controller.mark_failed.assert_called_once_with()
    cleanup.run.assert_awaited_once_with(None)
    recorder.clear_secrets.assert_called_once_with()
    controller.finish_cleanup.assert_called_once_with()


@pytest.mark.asyncio
async def test_operational_cleanup_failure_adds_note_to_workflow_error() -> None:
    controller = MagicMock()
    recorder = MagicMock()
    cleanup = AsyncMock()
    cleanup.run.side_effect = UpdateCleanupError("transport cleanup failed")
    runner = UpdateWorkflowRunner(
        status_controller=controller,
        status_recorder=recorder,
        cleanup=cleanup,
        timeout_s=10.0,
    )

    async def broken_workflow(_context: UpdateWorkflowContext) -> None:
        raise RuntimeError("workflow bug")

    runner.start(request=_wifi_request(), workflow=broken_workflow)
    task = runner.job_task
    assert task is not None

    with pytest.raises(RuntimeError, match="workflow bug") as exc_info:
        await task

    assert exc_info.value.__notes__ == ["Cleanup also failed: transport cleanup failed"]
    recorder.clear_secrets.assert_called_once_with()
    controller.finish_cleanup.assert_called_once_with()


@pytest.mark.asyncio
async def test_unexpected_cleanup_bug_propagates_instead_of_being_hidden() -> None:
    controller = MagicMock()
    recorder = MagicMock()
    cleanup = AsyncMock()
    cleanup.run.side_effect = TypeError("cleanup bug")
    runner = UpdateWorkflowRunner(
        status_controller=controller,
        status_recorder=recorder,
        cleanup=cleanup,
        timeout_s=10.0,
    )

    async def broken_workflow(_context: UpdateWorkflowContext) -> None:
        raise RuntimeError("workflow bug")

    runner.start(request=_wifi_request(), workflow=broken_workflow)
    task = runner.job_task
    assert task is not None

    with pytest.raises(TypeError, match="cleanup bug"):
        await task

    recorder.clear_secrets.assert_called_once_with()
    controller.finish_cleanup.assert_called_once_with()
